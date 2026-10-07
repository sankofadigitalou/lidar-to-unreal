"""Cut the survey window out of an orthophoto sheet, pixel-aligned with the heightmap.

    uv run tools/ortho_window.py --terrain out/terrain.json --sheet ORTHO.tif --out out/

Writes ortho_rgb_<tag>.png and ortho_nir_<tag>.png (if the sheet has a 4th band).

Made for DGT's ORTOS COG sheets (25 cm, RGB + NIR, 32000 x 20000 BigTIFF, JPEG-tiled, one plane per band), which
PIL cannot open. Only the tiles the window touches are read and decoded, so a 461 MB sheet costs seconds.
"""
import argparse
import os

import numpy as np
import tifffile
from PIL import Image

import l2u_common as c

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--terrain", required=True, help="terrain.json (or site.json)")
ap.add_argument("--sheet", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()

site = c.load_json(a.terrain)
x0, ytop, _, _, size_m = c.window(site)
tag = site.get("tag", "site")

tif = tifffile.TiffFile(a.sheet)
p = tif.pages[0]
res = p.tags["ModelPixelScaleTag"].value[0]
tie = p.tags["ModelTiepointTag"].value
ox, oy = tie[3], tie[4]
if p.planarconfig != tifffile.PLANARCONFIG.SEPARATE or not p.is_tiled:
    raise SystemExit("expects a tiled, planar sheet (one plane per band) like DGT's ORTOS COGs")
# Bind everything tifffile builds lazily BEFORE seeking: the first p.decode access reads the file and moves the
# pointer between our seek and read ("Not a JPEG file: starts with 0x00 0x01").
offs, counts, jt, dec = list(p.dataoffsets), list(p.databytecounts), p.jpegtables, p.decode
TW = p.tilewidth
ntx, nty = -(-p.imagewidth // TW), -(-p.imagelength // TW)
per = ntx * nty
bands = min(4, len(offs) // per)
c0, r0, n = int(round((x0 - ox) / res)), int(round((oy - ytop) / res)), int(round(size_m / res))
if not (0 <= c0 and c0 + n <= p.imagewidth and 0 <= r0 and r0 + n <= p.imagelength):
    raise SystemExit("the window is outside this sheet")

out = np.zeros((n, n, bands), np.uint8)
for b in range(bands):
    for ty in range(r0 // TW, (r0 + n - 1) // TW + 1):
        for tx in range(c0 // TW, (c0 + n - 1) // TW + 1):
            i = b * per + ty * ntx + tx
            tif.filehandle.seek(offs[i])
            t, _, _ = dec(tif.filehandle.read(counts[i]), i, jpegtables=jt)
            t = np.asarray(t).reshape(TW, TW)
            ty0, tx0 = ty * TW, tx * TW
            ys, ye = max(r0, ty0), min(r0 + n, ty0 + TW)
            xs, xe = max(c0, tx0), min(c0 + n, tx0 + TW)
            out[ys - r0:ye - r0, xs - c0:xe - c0, b] = t[ys - ty0:ye - ty0, xs - tx0:xe - tx0]
os.makedirs(a.out, exist_ok=True)
Image.fromarray(out[:, :, :3]).save(os.path.join(a.out, "ortho_rgb_%s.png" % tag))
if bands == 4:
    Image.fromarray(out[:, :, 3]).save(os.path.join(a.out, "ortho_nir_%s.png" % tag))
print("%dx%d px at %g m from sheet pixel (%d, %d); band means %s" % (n, n, res, c0, r0, out.reshape(-1, bands).mean(0).round(1)))
