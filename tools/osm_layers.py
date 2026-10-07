"""Road masks and place labels for the horizon rings, from OpenStreetMap JSON.

    uv run tools/osm_layers.py --terrain out/terrain.json --near out/osm_near.json --major out/osm_major.json --out out/

Writes roads_near.png (near ring, every road and track), roads_far.png (far ring, major roads) and labels.json
(the site, cities, towns, villages and named peaks: name, UE x/y cm, kind, ele). Greyscale masks, white = road,
north-west = pixel (0, 0), covering exactly the horizon rings of tools/horizon.py.
OpenStreetMap data (c) OpenStreetMap contributors, ODbL 1.0.
"""
import argparse
import json
import os

from PIL import Image, ImageDraw

import l2u_common as c

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--terrain", required=True)
ap.add_argument("--near", required=True, help="osm_near.json (tools/osm_fetch.py)")
ap.add_argument("--major", required=True, help="osm_major.json (tools/osm_fetch.py)")
ap.add_argument("--near-half-km", type=float, default=6.0)
ap.add_argument("--far-half-km", type=float, default=50.0)
ap.add_argument("--near-px-m", type=float, default=3.0)
ap.add_argument("--far-px-m", type=float, default=25.0)
ap.add_argument("--min-peak-m", type=float, default=0.0, help="drop named peaks lower than this")
ap.add_argument("--out", required=True)
a = ap.parse_args()

site = c.load_json(a.terrain)
e0, n0 = c.origin(site)
fwd, _ = c.transformers(site["crs"])
WIDTH_M = {"motorway": 24, "trunk": 16, "primary": 12, "secondary": 9, "tertiary": 7, "unclassified": 5,
           "residential": 5, "living_street": 4, "service": 3.5, "track": 3, "motorway_link": 8, "trunk_link": 7,
           "primary_link": 6, "tertiary_link": 5}


def lonlat_to_ue(lon, lat):
    e, n = fwd.transform(lon, lat)
    return (e - e0) * 100.0, -(n - n0) * 100.0


def draw(ways, half_m, px_m, out, min_px=1):
    n = int(round(2 * half_m / px_m))
    im = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(im)
    for w in ways:
        hw = w.get("tags", {}).get("highway")
        if hw not in WIDTH_M:
            continue
        pts = [lonlat_to_ue(p["lon"], p["lat"]) for p in w["geometry"]]
        pix = [((x / 100 + half_m) / px_m, (y / 100 + half_m) / px_m) for x, y in pts]
        d.line(pix, fill=255, width=max(min_px, int(round(WIDTH_M[hw] / px_m))), joint="curve")
    im.save(os.path.join(a.out, out))
    return n


os.makedirs(a.out, exist_ok=True)
near = [e for e in c.load_json(a.near)["elements"] if e["type"] == "way"]
major = c.load_json(a.major)["elements"]
major_ways = [e for e in major if e["type"] == "way"]
n1 = draw(near + major_ways, a.near_half_km * 1000, a.near_px_m, "roads_near.png")
n2 = draw(major_ways, a.far_half_km * 1000, a.far_px_m, "roads_far.png")

labels = [{"name": site.get("label", "Site"), "kind": "site", "x": 0.0, "y": 0.0, "ele": round(float(site["z0_m"]), 1)}]
for e in major:
    if e["type"] != "node":
        continue
    t = e.get("tags", {})
    kind = t.get("place") or t.get("natural")
    if kind not in ("city", "town", "village", "peak") or not t.get("name"):
        continue
    ele = t.get("ele")
    try:
        ele = float(ele.split()[0].replace(",", ".")) if ele else None
    except ValueError:
        ele = None
    if kind == "peak" and (ele is None or ele < a.min_peak_m):
        continue
    x, y = lonlat_to_ue(e["lon"], e["lat"])
    labels.append({"name": t["name"], "kind": kind, "x": round(x), "y": round(y), "ele": ele})
with open(os.path.join(a.out, "labels.json"), "w", encoding="utf-8") as f:
    json.dump(labels, f, indent=0, ensure_ascii=False)
print("roads_near %d px, roads_far %d px, %d labels %s" % (n1, n2, len(labels),
      {k: sum(1 for lb in labels if lb["kind"] == k) for k in ("site", "city", "town", "village", "peak")}))
