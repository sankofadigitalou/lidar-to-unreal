"""Horizon height grids around the survey window from Copernicus GLO-30, out to 50 km (or what you configure).

    uv run tools/horizon.py --terrain out/terrain.json --dem-dir copernicus/ --dtm DTM.tif --out out/

Writes horizon_<ring>.f32 (little-endian float32, UE cm, row-major from the north-west, x east, y south) and
horizon.json (grid sizes, datum offset, highest point) for unreal/horizon_mesh.py.

Two square rings centred on UE (0,0), by default: near +-6 km at 30 m, far +-50 km at 150 m. Each vertex height =
Copernicus (bilinear) + datum offset + earth-curvature drop with refraction (k 0.13, drop = d^2 / (2 R / (1 - k))).
The datum offset is the median of (DTM - Copernicus) over the DTM tile, so open ground at the window edge meets the
survey terrain. Vertices a finer surface covers are sunk: near ring inside the survey window (3 m), far ring inside the
near ring (40 m), so the coarse rings never poke through.

--dem-dir holds the GLO-30 DSM tiles that cover the far ring (Copernicus_DSM_COG_10_N..._DEM.tif, EPSG:4326).
Override the rings in terrain.json/site.json under "horizon": {"rings": {"near": {...}, "far": {...}}}.
Copernicus DEM GLO-30: (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018, provided under
COPERNICUS by the European Union and ESA.
"""
import argparse
import glob
import math
import os

import numpy as np
import tifffile

import l2u_common as c

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--terrain", required=True)
ap.add_argument("--dem-dir", required=True)
ap.add_argument("--dtm", required=True, help="the survey DTM tile, for the datum offset")
ap.add_argument("--out", required=True)
a = ap.parse_args()

site = c.load_json(a.terrain)
_, _, _, _, size_m = c.window(site)
e0, n0 = c.origin(site)
z0 = float(site["z0_m"])
K = 0.13
R_EFF = 6371000.0 / (1 - K)
rings = {"near": {"half_m": 6000.0, "step_m": 30.0, "sink_half_m": float(math.floor(size_m / 2)), "sink_m": 3.0},
         "far": {"half_m": 50000.0, "step_m": 150.0, "sink_half_m": 5900.0, "sink_m": 40.0}}
for k, v in site.get("horizon", {}).get("rings", {}).items():
    rings.setdefault(k, {}).update(v)
_, to_lonlat = c.transformers(site["crs"])

tiles = []
for f in sorted(glob.glob(os.path.join(a.dem_dir, "*.tif"))):
    with tifffile.TiffFile(f) as t:
        pg = t.pages[0]
        tie = pg.tags["ModelTiepointTag"].value
        sc = pg.tags["ModelPixelScaleTag"].value
        tiles.append((tie[3], tie[4], sc[0], sc[1], pg.asarray().astype(np.float32)))
if not tiles:
    raise SystemExit("no GeoTIFFs in %s" % a.dem_dir)


# All GLO-30 tiles sit on one global grid (whole-degree origins, the same pixel size within a latitude band), so a
# bilinear sample takes its four pixel centres from whichever tiles hold them: no seam between tiles.
DX, DY = tiles[0][2], tiles[0][3]
GX, GY = tiles[0][0], tiles[0][1]
if any(abs(t[2] - DX) > 1e-12 or abs(t[3] - DY) > 1e-12 for t in tiles):
    raise SystemExit("the DEM tiles have different pixel sizes (above 50 deg latitude GLO-30 widens them); "
                     "resample them to one grid first")


def pixel_value(lon_c, lat_c):
    """Value of the pixel whose centre is (lon_c, lat_c); NaN where no tile holds it."""
    out = np.full(lon_c.shape, np.nan, np.float32)
    for x0, y0, dx, dy, arr in tiles:
        h, w = arr.shape
        i = np.floor((lon_c - x0) / dx).astype(int)
        j = np.floor((y0 - lat_c) / dy).astype(int)
        ok = (i >= 0) & (i < w) & (j >= 0) & (j < h) & np.isnan(out)
        out[ok] = arr[j[ok], i[ok]]
    return out


def dem_height(lon, lat):
    u = (lon - GX) / DX - 0.5                                    # pixel-is-area tiepoint: centres at +0.5
    v = (GY - lat) / DY - 0.5
    i, j = np.floor(u), np.floor(v)
    fu, fv = (u - i).astype(np.float32), (v - j).astype(np.float32)
    lon_c = lambda k: GX + (i + k + 0.5) * DX
    lat_c = lambda k: GY - (j + k + 0.5) * DY
    a00, a10 = pixel_value(lon_c(0), lat_c(0)), pixel_value(lon_c(1), lat_c(0))
    a01, a11 = pixel_value(lon_c(0), lat_c(1)), pixel_value(lon_c(1), lat_c(1))
    return a00 * (1 - fu) * (1 - fv) + a10 * fu * (1 - fv) + a01 * (1 - fu) * fv + a11 * fu * fv


# datum offset: survey DTM vs Copernicus, every 10th DTM pixel
g = c.GeoTiff(a.dtm)
dtm = g.read().astype(np.float32)
jj, ii = np.mgrid[0:g.height:10, 0:g.width:10]
lon, lat = to_lonlat.transform(g.ox + (ii + 0.5) * g.res, g.oy - (jj + 0.5) * g.res)
diff = dtm[jj, ii] - dem_height(np.asarray(lon), np.asarray(lat))
offset = float(np.nanmedian(diff))

meta = {"datum_offset_m": round(offset, 3),
        "datum_offset_iqr_m": [round(float(np.nanpercentile(diff, q)), 3) for q in (25, 75)],
        "z0_m": z0, "refraction_k": K, "rings": {}}
os.makedirs(a.out, exist_ok=True)
for name, r in rings.items():
    half, step, sink_half, sink = r["half_m"], r["step_m"], r["sink_half_m"], r["sink_m"]
    n = int(round(2 * half / step)) + 1
    xs = np.linspace(-half, half, n)
    X, Y = np.meshgrid(xs, xs)                                   # UE metres, y south
    lon, lat = to_lonlat.transform(e0 + X, n0 - Y)
    h = dem_height(np.asarray(lon), np.asarray(lat))
    missing = int(np.isnan(h).sum())
    h = np.where(np.isnan(h), np.nanmin(h), h)
    z_m = h + offset - (X ** 2 + Y ** 2) / (2 * R_EFF) - z0
    inner = (np.abs(X) < sink_half) & (np.abs(Y) < sink_half)
    z_m = np.where(inner, z_m - sink, z_m)
    (z_m * 100.0).astype("<f4").tofile(os.path.join(a.out, "horizon_%s.f32" % name))
    top = np.unravel_index(np.argmax(np.where(inner, -1e9, z_m)), z_m.shape)
    meta["rings"][name] = {"n": n, "half_m": half, "step_m": step, "sink_half_m": sink_half, "missing": missing,
                           "z_min_m": round(float(z_m.min()), 1), "z_max_m": round(float(z_m.max()), 1),
                           "highest_point": {"x_km": round(float(X[top]) / 1000, 2), "y_km": round(float(Y[top]) / 1000, 2),
                                             "altitude_m": round(float(h[top] + offset), 1)}}
    if missing:
        print("WARNING: ring %s has %d vertices outside the DEM tiles (filled with the lowest height)" % (name, missing))
c.save_json(meta, os.path.join(a.out, "horizon.json"))
print("datum offset %.2f m; %s" % (offset, {k: (v["n"], v["z_min_m"], v["z_max_m"]) for k, v in meta["rings"].items()}))
