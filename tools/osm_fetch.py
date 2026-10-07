"""Download the OpenStreetMap roads, places and peaks around the site from the Overpass API.

    uv run tools/osm_fetch.py --terrain out/terrain.json --out out/

Writes osm_near.json (every highway way inside the near ring) and osm_major.json (major roads plus named cities,
towns, villages and peaks inside the far ring), the inputs of tools/osm_layers.py. Two requests, one per file;
please keep it that way on the public Overpass server. OpenStreetMap data (c) OpenStreetMap contributors, ODbL 1.0.
"""
import argparse
import json
import os
import urllib.parse
import urllib.request

import l2u_common as c

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--terrain", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--near-km", type=float, default=6.0)
ap.add_argument("--far-km", type=float, default=50.0)
ap.add_argument("--endpoint", default="https://overpass-api.de/api/interpreter")
a = ap.parse_args()

site = c.load_json(a.terrain)
e0, n0 = c.origin(site)
_, to_lonlat = c.transformers(site["crs"])


def bbox(km):
    d = km * 1000.0
    lons, lats = to_lonlat.transform([e0 - d, e0 + d, e0 - d, e0 + d], [n0 - d, n0 - d, n0 + d, n0 + d])
    return "%.6f,%.6f,%.6f,%.6f" % (min(lats), min(lons), max(lats), max(lons))     # Overpass: S,W,N,E


QUERIES = {
    "osm_near.json": '[out:json][timeout:120];way["highway"](%s);out geom;' % bbox(a.near_km),
    "osm_major.json": ('[out:json][timeout:180];('
                       'way["highway"~"^(motorway|trunk|primary|secondary|motorway_link|trunk_link|primary_link)$"](%(b)s);'
                       'node["place"~"^(city|town|village)$"]["name"](%(b)s);'
                       'node["natural"="peak"]["name"](%(b)s););out geom;') % {"b": bbox(a.far_km)},
}
os.makedirs(a.out, exist_ok=True)
for name, q in QUERIES.items():
    req = urllib.request.Request(a.endpoint, data=urllib.parse.urlencode({"data": q}).encode(),
                                 headers={"User-Agent": "lidar-to-unreal (github.com/sankofadigitalou/lidar-to-unreal)"})
    with urllib.request.urlopen(req, timeout=240) as r:
        data = json.load(r)
    with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
        json.dump(data, f)
    print("%s: %d elements" % (name, len(data.get("elements", []))))
