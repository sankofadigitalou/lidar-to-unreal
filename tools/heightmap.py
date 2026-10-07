"""Cut the survey window out of a DTM (and optional DSM) tile and write Unreal terrain inputs.

    uv run tools/heightmap.py --site site.json --dtm DTM.tif [--dsm DSM.tif] --out out/

Writes to --out:
  heightmap_<n>.png  16-bit greyscale over the window's own height range: Landscape "Import from File" or
                     Mesh Terrain "Import Heightmap"
  canopy_<n>.png     8-bit, DSM - DTM in decimetres, clipped to 25.5 m (where trees and buildings stand), if --dsm
  terrain.json       site.json + the measured heights + the import numbers for both terrain types; every later step
                     reads this file

Made for the 50 cm DTM/DSM tiles of Portugal's Direção-Geral do Território (2000 x 2000 float32, ETRS89 / PT-TM06,
CC BY 4.0), but any single-band north-up GeoTIFF in a metric CRS works.
"""
import argparse
import math
import os

import numpy as np
from PIL import Image

import l2u_common as c

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--site", required=True)
ap.add_argument("--dtm", required=True, help="bare-earth model (DGT: MDT)")
ap.add_argument("--dsm", help="surface model incl. trees and roofs (DGT: MDS)")
ap.add_argument("--out", required=True)
a = ap.parse_args()

site = c.load_json(a.site)
x0, ytop, n, res, size_m = c.window(site)
g = c.GeoTiff(a.dtm)
if abs(g.res - res) > 1e-9:
    raise SystemExit("site res_m %.3f != DTM pixel size %.3f" % (res, g.res))
col, row = g.pixel_of(x0, ytop)
if not (0 <= col and col + n <= g.width and 0 <= row and row + n <= g.height):
    raise SystemExit("the window (pixel %d, %d, %d px) is outside this %dx%d tile" % (col, row, n, g.width, g.height))


def crop(path):
    arr = c.GeoTiff(path).read()[row:row + n, col:col + n]
    if np.isnan(arr).any():
        raise SystemExit("%s: %d nodata cells inside the window; fill them before import" % (path, np.isnan(arr).sum()))
    return arr


t = crop(a.dtm)
zmin, zmax = float(t.min()), float(t.max())
rng = zmax - zmin
if math.isclose(rng, 0.0):
    raise SystemExit("the window is flat: nothing to import")
os.makedirs(a.out, exist_ok=True)
Image.fromarray(np.round((t - zmin) / rng * 65535).astype(np.uint16)).save(os.path.join(a.out, "heightmap_%d.png" % n))
if a.dsm:
    chm = np.clip(crop(a.dsm) - t, 0, 25.5)
    Image.fromarray(np.round(chm * 10).astype(np.uint8)).save(os.path.join(a.out, "canopy_%d.png" % n))

z0 = round(zmin + rng / 2, 2)
e0, n0 = c.origin(site)
size_xy_cm = round((n - 1) * res * 100, 1)
size_z_cm = round(rng * 100, 1)
terrain = dict(site)
terrain.update({
    "origin": {"e": e0, "n": n0},
    "z_min_m": round(zmin, 3), "z_max_m": round(zmax, 3), "range_m": round(rng, 3),
    "z0_m": z0,
    "landscape": {"file": "heightmap_%d.png" % n, "scale_x": res * 100, "scale_y": res * 100,
                  "scale_z": round(rng / 512.0 * 100.0, 4), "actor_z_cm": 0.0},
    "mesh_terrain": {"file": "heightmap_%d.png" % n, "size_x_cm": size_xy_cm, "size_y_cm": size_xy_cm,
                     "size_z_cm": size_z_cm, "actor_z_cm": -size_z_cm / 2},
    "sources": {"dtm": os.path.basename(a.dtm), "dsm": os.path.basename(a.dsm) if a.dsm else None,
                "dtm_pixel": [col, row]},
})
c.save_json(terrain, os.path.join(a.out, "terrain.json"))
print("""heightmap_{n}.png  window {n} px = {sm:.1f} m, heights {zmin:.2f} .. {zmax:.2f} m (range {rng:.2f} m)
UE (0,0) = map ({e0:.2f}, {n0:.2f}); UE Z 0 = {z0:.2f} m real altitude
Landscape  > Import from File: Scale X = Y = {sxy:g}, Scale Z = {sz:.4f}, actor Z 0
Mesh Terrain > Import Heightmap: Size X = Y = {mxy:g}, Size Z = {mz:g}, then actor Z = {az:g} (unreal/mesh_terrain_place.py)""".format(
    n=n, sm=size_m, zmin=zmin, zmax=zmax, rng=rng, e0=e0, n0=n0, z0=z0, sxy=res * 100, sz=rng / 512.0 * 100.0,
    mxy=size_xy_cm, mz=size_z_cm, az=-size_z_cm / 2))
