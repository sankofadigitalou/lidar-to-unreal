"""Shared helpers: site/terrain config, GeoTIFF georeferencing, CRS <-> Unreal coordinates.

Unreal axes used everywhere in this repo: +X = east, +Y = grid SOUTH, +Z = up, centimetres.
UE (0, 0) is the centre of the survey window's centre pixel; UE Z 0 is the window's mid-height (terrain.json z0_m).
"""
import json
import os

import numpy as np
import tifffile


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")


class GeoTiff:
    """A single-band, north-up GeoTIFF in a projected CRS (metres): pixel size, top-left corner, nodata."""

    def __init__(self, path):
        self.path = path
        with tifffile.TiffFile(path) as t:
            p = t.pages[0]
            self.res = float(p.tags["ModelPixelScaleTag"].value[0])
            tie = p.tags["ModelTiepointTag"].value
            self.ox, self.oy = float(tie[3]), float(tie[4])        # map coordinates of the top-left corner
            nod = p.tags.get("GDAL_NODATA")
            self.nodata = float(str(nod.value).strip("\x00 ")) if nod is not None else None
            self.height, self.width = p.imagelength, p.imagewidth

    def read(self):
        """The whole band as float64; nodata cells become NaN."""
        a = tifffile.imread(self.path).astype(np.float64)
        if self.nodata is not None:
            a[a == self.nodata] = np.nan
        return a

    def pixel_of(self, x0, ytop):
        """Column/row of the pixel whose top-left corner is (x0, ytop)."""
        return int(round((x0 - self.ox) / self.res)), int(round((self.oy - ytop) / self.res))


def window(site):
    """(x0, ytop, size_px, res_m, size_m) of the survey window from site.json / terrain.json."""
    w = site["window"]
    n, res = int(w["size_px"]), float(w["res_m"])
    return float(w["x0"]), float(w["ytop"]), n, res, n * res


def origin(site):
    """Map coordinates of UE (0, 0): the centre of the window's centre pixel."""
    x0, ytop, n, res, _ = window(site)
    return x0 + (n // 2 + 0.5) * res, ytop - (n // 2 + 0.5) * res


def transformers(crs):
    """(lon/lat -> CRS, CRS -> lon/lat) pyproj transformers, always x/y order."""
    import pyproj
    return (pyproj.Transformer.from_crs(4326, crs, always_xy=True),
            pyproj.Transformer.from_crs(crs, 4326, always_xy=True))


def map_to_ue(e, n, e0, n0):
    """Map metres -> UE cm (+X east, +Y south)."""
    return (np.asarray(e) - e0) * 100.0, -(np.asarray(n) - n0) * 100.0


def ue_to_map(x_cm, y_cm, e0, n0):
    return e0 + np.asarray(x_cm) / 100.0, n0 - np.asarray(y_cm) / 100.0
