"""Read a classified LiDAR point cloud (LAZ/LAS) and write game inputs for the survey window.

    uv run tools/laz_extract.py --terrain out/terrain.json --laz TILE.laz --out out/

Writes to --out (all positions in UE cm relative to UE (0,0), +X east, +Y south, Z relative to terrain.json z0_m):
  trees_<tag>.csv      one row per detected tree: ue_x_cm, ue_y_cm, ue_z_cm (ground under it), height_m, crown_r_m
  buildings_<tag>.csv  building-class points gridded to 0.5 m cells
  water_<tag>.csv      water-class points gridded to 0.5 m cells
  classes_<tag>.png    top-down class map at 0.25 m (ground tan, vegetation greens, buildings red, water blue)
  rgb3d_<tag>.jpg      an oblique splat render of the coloured points around the centre (if the points carry RGB)

Needs ASPRS classes (2 ground, 4/5 medium/high vegetation, 6 building, 9 water); DGT's 2024 LiDAR has them.
Trees = local maxima of the smoothed canopy height model, >= 3 m tall and >= 3 m apart; crown radius = median
distance along 8 rays to where the crown falls below half its height (capped 8 m).
"""
import argparse
import csv
import os

import laspy
import numpy as np
from PIL import Image
from scipy import ndimage

import l2u_common as c

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--terrain", required=True)
ap.add_argument("--laz", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--min-tree-m", type=float, default=3.0)
a = ap.parse_args()

site = c.load_json(a.terrain)
x0, y1, _, _, L = c.window(site)            # y1 = top edge
x1, y0 = x0 + L, y1 - L
zmid = float(site["z0_m"])
tag = site.get("tag", "site")
cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
os.makedirs(a.out, exist_ok=True)

las = laspy.read(a.laz)
X, Y, Z = np.asarray(las.x), np.asarray(las.y), np.asarray(las.z)
m = (X >= x0) & (X < x1) & (Y > y0) & (Y <= y1)
X, Y, Z, C = X[m], Y[m], Z[m], np.asarray(las.classification)[m]
has_rgb = "red" in las.point_format.dimension_names
print("%s points in the window" % format(int(m.sum()), ","))
if not m.any():
    raise SystemExit("no points inside the window: wrong tile or wrong CRS?")


def ue(x, y):
    return (x - cx) * 100, (cy - y) * 100


# ground and vegetation-top rasters at 0.5 m
res = 0.5
n = int(round(L / res))
col = np.clip(((X - x0) / res).astype(int), 0, n - 1)
row = np.clip(((y1 - Y) / res).astype(int), 0, n - 1)


def rmax(sel, fill=np.nan):
    r = np.full(n * n, -np.inf)
    np.maximum.at(r, row[sel] * n + col[sel], Z[sel])
    r[np.isinf(r)] = fill
    return r.reshape(n, n)


g = C == 2
if not g.any():
    raise SystemExit("no ground-class (2) points: the cloud is not classified")
gr = np.full(n * n, np.nan)
cnt, s = np.zeros(n * n), np.zeros(n * n)
np.add.at(s, row[g] * n + col[g], Z[g])
np.add.at(cnt, row[g] * n + col[g], 1)
gr[cnt > 0] = s[cnt > 0] / cnt[cnt > 0]
gr = gr.reshape(n, n)
# fill ground holes (under buildings, dense crowns) from the nearest valid cell
idx = ndimage.distance_transform_edt(np.isnan(gr), return_distances=False, return_indices=True)
gr = gr[tuple(idx)]
veg = rmax(np.isin(C, (4, 5)), fill=np.nan)
chm = np.nan_to_num(veg - gr, nan=0.0)
chm[chm < 0] = 0

sm = ndimage.gaussian_filter(chm, 1.0)
peaks = (sm == ndimage.maximum_filter(sm, size=7)) & (sm >= a.min_tree_m)
rows, cols = np.nonzero(peaks)
rays = [(np.cos(t), np.sin(t)) for t in np.linspace(0, 2 * np.pi, 8, endpoint=False)]
with open(os.path.join(a.out, "trees_%s.csv" % tag), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["ue_x_cm", "ue_y_cm", "ue_z_cm", "height_m", "crown_r_m"])
    for r_, c_ in zip(rows, cols):
        hgt = chm[r_, c_]
        rad = []
        for dx, dy in rays:
            k = 1
            while k < 16:
                rr, cc = int(round(r_ + dy * k)), int(round(c_ + dx * k))
                if not (0 <= rr < n and 0 <= cc < n) or chm[rr, cc] < hgt / 2:
                    break
                k += 1
            rad.append(k * res)
        ux, uy = ue(x0 + (c_ + 0.5) * res, y1 - (r_ + 0.5) * res)
        w.writerow([round(ux), round(uy), round((gr[r_, c_] - zmid) * 100), round(hgt, 2), round(float(np.median(rad)), 2)])
print("%d trees >= %g m%s" % (len(rows), a.min_tree_m, "; tallest %.1f m" % chm[peaks].max() if len(rows) else ""))

for name, cls in (("buildings", 6), ("water", 9)):
    sel = C == cls
    cells = np.unique(np.stack([row[sel], col[sel]], 1), axis=0) if sel.any() else np.zeros((0, 2), int)
    with open(os.path.join(a.out, "%s_%s.csv" % (name, tag)), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ue_x_cm", "ue_y_cm", "ue_z_cm"])
        for r_, c_ in cells:
            ux, uy = ue(x0 + (c_ + 0.5) * res, y1 - (r_ + 0.5) * res)
            w.writerow([round(ux), round(uy), round((gr[r_, c_] - zmid) * 100)])
    print("%s: %s points in %d half-metre cells" % (name, format(int(sel.sum()), ","), len(cells)))

# class map, 0.25 m, highest point per cell wins
q = 0.25
nq = int(round(L / q))
cq = np.clip(((X - x0) / q).astype(int), 0, nq - 1)
rq = np.clip(((y1 - Y) / q).astype(int), 0, nq - 1)
order = np.argsort(Z)
top = np.full(nq * nq, -1)
top[rq[order] * nq + cq[order]] = order
pal = {2: (214, 196, 140), 3: (150, 214, 90), 4: (70, 170, 60), 5: (30, 110, 40), 6: (220, 40, 30), 9: (40, 110, 230)}
img = np.full((nq * nq, 3), 60, np.uint8)
ok = top >= 0
img[ok] = np.array([pal.get(int(k), (120, 120, 120)) for k in range(256)], np.uint8)[C[top[ok]]]
Image.fromarray(img.reshape(nq, nq, 3)).save(os.path.join(a.out, "classes_%s.png" % tag))

if has_rgb:
    # oblique splat render of the coloured points within 110 m of the centre, camera from the south-south-west
    R, G, B = (np.asarray(las[k])[m] >> 8 for k in ("red", "green", "blue"))
    sel = (np.abs(X - cx) < 110) & (np.abs(Y - cy) < 110)
    px, py, pz = X[sel] - cx, Y[sel] - cy, Z[sel] - zmid
    az, el, dist = np.radians(200), np.radians(35), 230.0
    cam = np.array([np.sin(az) * np.cos(el), np.cos(az) * np.cos(el), np.sin(el)]) * dist
    fwd = -cam / np.linalg.norm(cam)
    right = np.cross(fwd, [0, 0, 1])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    P = np.stack([px, py, pz], 1) - cam
    depth = P @ fwd
    W, H, f_ = 1600, 900, 1400.0
    u = (W / 2 + (P @ right / depth) * f_).astype(int)
    v = (H / 2 - (P @ up / depth) * f_).astype(int)
    k = (u >= 0) & (u < W - 1) & (v >= 0) & (v < H - 1) & (depth > 1)
    o = np.argsort(-depth[k])                # far first, near overwrites
    canvas = np.zeros((H, W, 3), np.uint8)
    canvas[:] = (150, 170, 200)
    uu, vv = u[k][o], v[k][o]
    rgb = np.stack([R[sel][k][o], G[sel][k][o], B[sel][k][o]], 1).astype(np.uint8)
    for du in (0, 1):
        for dv in (0, 1):
            canvas[vv + dv, uu + du] = rgb
    Image.fromarray(canvas).save(os.path.join(a.out, "rgb3d_%s.jpg" % tag), quality=90)
print("wrote", a.out)
