"""End-to-end checks on synthetic data with known answers: a tilted plane DTM, one cone-shaped tree, two DEM tiles.

Run: uv run pytest
"""
import csv
import json
import os
import subprocess
import sys

import laspy
import numpy as np
import pytest
import tifffile
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
CRS = "EPSG:3763"
OX, OY, RES, N = 0.0, 0.0, 0.5, 200                  # a 100 m x 100 m DTM tile, 0.5 m cells


def run(tool, *args):
    r = subprocess.run([sys.executable, os.path.join(TOOLS, tool), *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    return r.stdout


def write_geotiff(path, arr, ox, oy, res, nodata=None):
    tags = [(33550, "d", 3, (res, res, 0.0), False), (33922, "d", 6, (0.0, 0.0, 0.0, ox, oy, 0.0), False)]
    if nodata is not None:
        tags.append((42113, "s", 0, str(nodata), False))
    tifffile.imwrite(path, arr.astype(np.float32), extratags=tags)


@pytest.fixture
def site(tmp_path):
    jj, ii = np.mgrid[0:N, 0:N]
    dtm = 400.0 + ii * 0.05 + jj * 0.02                  # rises 5 m to the east, 2 m to the south over the tile
    write_geotiff(tmp_path / "dtm.tif", dtm, OX, OY, RES)
    dsm = dtm.copy()
    dsm[100:110, 100:110] += 6.0                          # a 6 m block: canopy
    write_geotiff(tmp_path / "dsm.tif", dsm, OX, OY, RES)
    s = {"label": "Test", "tag": "t", "crs": CRS, "window": {"x0": OX + 23 * RES, "ytop": OY - 23 * RES, "size_px": 127, "res_m": RES}}
    (tmp_path / "site.json").write_text(json.dumps(s))
    return tmp_path


def test_heightmap_numbers_and_pixels(site):
    out = site / "out"
    run("heightmap.py", "--site", str(site / "site.json"), "--dtm", str(site / "dtm.tif"), "--dsm", str(site / "dsm.tif"), "--out", str(out))
    t = json.loads((out / "terrain.json").read_text())
    # window = pixels 23..149 in both axes: heights 400 + 23*0.07 .. 400 + 149*0.07
    assert t["z_min_m"] == pytest.approx(400 + 23 * 0.07, abs=1e-3)
    assert t["z_max_m"] == pytest.approx(400 + 149 * 0.07, abs=1e-3)
    assert t["mesh_terrain"]["size_x_cm"] == 126 * 50
    assert t["mesh_terrain"]["actor_z_cm"] == pytest.approx(-t["mesh_terrain"]["size_z_cm"] / 2)
    assert t["origin"] == {"e": OX + 23 * RES + 63.5 * RES, "n": OY - 23 * RES - 63.5 * RES}
    hm = np.array(Image.open(out / "heightmap_127.png"))
    assert hm.dtype == np.uint16 and hm[0, 0] == 0 and hm[-1, -1] == 65535
    assert hm[0, -1] > hm[-1, 0]                          # east rises faster than south
    canopy = np.array(Image.open(out / "canopy_127.png"))
    assert canopy[100 - 23, 100 - 23] == 60 and canopy[0, 0] == 0


def test_heightmap_refuses_nodata(site):
    dtm = np.full((N, N), 400.0)
    dtm[60, 60] = -999.0
    write_geotiff(site / "holes.tif", dtm, OX, OY, RES, nodata=-999)
    r = subprocess.run([sys.executable, os.path.join(TOOLS, "heightmap.py"), "--site", str(site / "site.json"),
                        "--dtm", str(site / "holes.tif"), "--out", str(site / "o")], capture_output=True, text=True)
    assert r.returncode != 0 and "nodata" in (r.stderr + r.stdout)


def test_laz_finds_the_one_tree_where_it_stands(site):
    run("heightmap.py", "--site", str(site / "site.json"), "--dtm", str(site / "dtm.tif"), "--out", str(site / "out"))
    t = json.loads((site / "out" / "terrain.json").read_text())
    rng = np.random.default_rng(1)
    gx, gy = rng.uniform(OX, OX + 100, 40000), rng.uniform(OY - 100, OY, 40000)
    ground_z = lambda x, y: 400.0 + (x - OX) / RES * 0.05 + (OY - y) / RES * 0.02
    tx, ty, th, tr = OX + 40.25, OY - 52.75, 9.0, 2.5      # a 9 m cone, crown radius 2.5 m
    ang, rad = rng.uniform(0, 2 * np.pi, 6000), tr * np.sqrt(rng.uniform(0, 1, 6000))
    vx, vy = tx + rad * np.cos(ang), ty + rad * np.sin(ang)
    vz = ground_z(vx, vy) + th * (1 - rad / tr * 0.4)
    hdr = laspy.LasHeader(point_format=3, version="1.2")
    hdr.scales, hdr.offsets = np.array([0.01, 0.01, 0.01]), np.array([OX, OY - 100, 0])
    las = laspy.LasData(hdr)
    las.x, las.y = np.concatenate([gx, vx]), np.concatenate([gy, vy])
    las.z = np.concatenate([ground_z(gx, gy), vz])
    las.classification = np.concatenate([np.full(gx.size, 2), np.full(vx.size, 5)]).astype(np.uint8)
    las.write(str(site / "cloud.las"))
    run("laz_extract.py", "--terrain", str(site / "out" / "terrain.json"), "--laz", str(site / "cloud.las"), "--out", str(site / "out"))
    rows = list(csv.DictReader(open(site / "out" / "trees_t.csv")))
    assert len(rows) == 1
    r = {k: float(v) for k, v in rows[0].items()}
    e0, n0 = t["origin"]["e"], t["origin"]["n"]
    assert r["ue_x_cm"] == pytest.approx((tx - e0) * 100, abs=75)          # within 0.75 m of the real trunk
    assert r["ue_y_cm"] == pytest.approx(-(ty - n0) * 100, abs=75)
    assert r["height_m"] == pytest.approx(th, abs=1.0)
    assert r["ue_z_cm"] == pytest.approx((ground_z(tx, ty) - t["z0_m"]) * 100, abs=25)


def test_horizon_has_no_step_at_a_tile_seam(site, tmp_path):
    """Two DEM tiles of one smooth slope: the rings must stay smooth across the seam between them.
    Control: the same check on a deliberately stepped pair of tiles must fail. (The original Agoro Camp builder, which
    interpolated inside each tile separately, fails the smooth case: ~170 m error at the seam.)"""
    run("heightmap.py", "--site", str(site / "site.json"), "--dtm", str(site / "dtm.tif"), "--out", str(site / "out"))
    terrain = json.loads((site / "out" / "terrain.json").read_text())
    terrain["horizon"] = {"rings": {"near": {"half_m": 6000.0, "step_m": 100.0, "sink_m": 0.0},       # no sink bands:
                                    "far": {"half_m": 20000.0, "step_m": 500.0, "sink_m": 0.0}}}    # they are steps too
    (site / "out" / "terrain.json").write_text(json.dumps(terrain))
    import pyproj
    lon0, lat0 = pyproj.Transformer.from_crs(CRS, 4326, always_xy=True).transform(terrain["origin"]["e"], terrain["origin"]["n"])
    n, d = 600, 1 / 600.0                                   # 6 arc-second cells

    def tiles(step_m, folder):
        os.makedirs(folder, exist_ok=True)
        seam = round((lat0 + 0.05) / d) * d                  # a tile seam ~5 km north of the site, on the pixel grid
        west = round((lon0 - 0.5) / d) * d
        for k, top in enumerate((seam, seam + 1)):           # tile 0 south of the seam, tile 1 north of it
            jj, ii = np.mgrid[0:n, 0:n]
            lat = top - (jj + 0.5) * d
            # a steep linear slope: bilinear interpolation reproduces it exactly, a nearest-pixel shortcut at the
            # seam is off by up to half a cell's rise (~170 m here)
            arr = 300.0 + (lat - lat0) * 200000.0 + (step_m if k == 1 else 0.0)
            write_geotiff(os.path.join(folder, "dem_%d.tif" % k), arr, west, top, d)
        return folder

    def worst_jump(folder):
        out = str(site / ("h_" + os.path.basename(folder)))
        run("horizon.py", "--terrain", str(site / "out" / "terrain.json"), "--dem-dir", folder, "--dtm", str(site / "dtm.tif"), "--out", out)
        meta = json.loads(open(os.path.join(out, "horizon.json")).read())
        worst = 0.0
        for ring in ("near", "far"):                         # the near ring's 100 m rows always cross the seam band
            r = meta["rings"][ring]
            z = np.fromfile(os.path.join(out, "horizon_%s.f32" % ring), "<f4").reshape(r["n"], r["n"])
            dz = np.diff(z, axis=0)                          # row to row (north -> south)
            worst = max(worst, float(np.abs(dz - np.median(dz)).max()))
        return worst

    smooth = worst_jump(tiles(0.0, str(tmp_path / "smooth")))
    stepped = worst_jump(tiles(50.0, str(tmp_path / "stepped")))
    assert stepped > 3000                                    # the control sees a 50 m step
    assert smooth < 300                                      # only earth curvature bends the rows (< 1.4 m here)
