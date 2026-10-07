"""Write a site.json: a survey window snapped to the pixel grid of your DTM tile, centred on a lat/lon.

    uv run tools/site_init.py --dtm DTM.tif --lat 40.3217 --lon -7.6114 --crs EPSG:3763 --size 1009 \
        --label "Torre" --out site.json

--size is the window in pixels per side and must be an Unreal Landscape size (505, 1009, 2017, ...). The window must
lie inside the one tile; mosaic neighbouring tiles first (for example with gdal_merge.py) if it does not.
Everything downstream reads site.json (or the terrain.json the heightmap step writes from it).
"""
import argparse

import l2u_common as c

UE_SIZES = (127, 253, 505, 1009, 2017, 4033, 8129)

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--dtm", required=True, help="the DTM GeoTIFF tile the window is snapped to")
ap.add_argument("--lat", type=float, required=True)
ap.add_argument("--lon", type=float, required=True)
ap.add_argument("--crs", required=True, help="the tile's projected CRS, e.g. EPSG:3763 (ETRS89 / PT-TM06)")
ap.add_argument("--size", type=int, default=1009, choices=UE_SIZES)
ap.add_argument("--label", default="Site")
ap.add_argument("--tag", default="site", help="suffix for output file names")
ap.add_argument("--out", default="site.json")
a = ap.parse_args()

g = c.GeoTiff(a.dtm)
fwd, _ = c.transformers(a.crs)
e, n = fwd.transform(a.lon, a.lat)
col, row = int((e - g.ox) // g.res), int((g.oy - n) // g.res)
h = a.size // 2
if not (h <= col < g.width - h and h <= row < g.height - h):
    raise SystemExit("a %d px window around pixel (%d, %d) does not fit inside the %dx%d tile; "
                     "mosaic the neighbouring tiles first" % (a.size, col, row, g.width, g.height))
site = {
    "label": a.label,
    "tag": a.tag,
    "crs": a.crs,
    "window": {"x0": g.ox + (col - h) * g.res, "ytop": g.oy - (row - h) * g.res, "size_px": a.size, "res_m": g.res},
}
c.save_json(site, a.out)
e0, n0 = c.origin(site)
print("wrote %s: window %d px = %.1f m, UE (0,0) = map (%.2f, %.2f), %.1f m from the requested point"
      % (a.out, a.size, a.size * g.res, e0, n0, ((e0 - e) ** 2 + (n0 - n) ** 2) ** 0.5))
