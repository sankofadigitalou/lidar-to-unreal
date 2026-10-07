# lidar-to-unreal

Turn free public data into a **1:1 playable twin of a real place in Unreal Engine 5.8**: the ground from a 50 cm LiDAR
terrain model, every tree where it really stands, and the real horizon out to 50 km.

I built this for [Agoro Camp](https://agoro.games), a game about the year I spent building an off-grid camp on a
hillside in central Portugal. The camp in the game sits where the camp sits. This repository is that pipeline,
taken out of the game and made general, so anyone can build a playable twin of a place from open data.

| Step | Tool | In | Out |
|---|---|---|---|
| 1 | `tools/site_init.py` | a DTM tile + a lat/lon | `site.json`: a survey window snapped to the tile's pixel grid |
| 2 | `tools/heightmap.py` | DTM (+ DSM) tile | 16-bit heightmap, canopy map, `terrain.json` with the Landscape **and** Mesh Terrain import numbers |
| 3 | `tools/laz_extract.py` | classified LiDAR point cloud (LAZ) | every tree ≥ 3 m (position, ground height, height, crown radius), buildings, water, a class map |
| 4 | `tools/ortho_window.py` | orthophoto sheet (optional) | RGB + near-infrared image, pixel-aligned with the heightmap |
| 5 | `tools/horizon.py` | Copernicus GLO-30 DEM tiles | two height rings, ±6 km and ±50 km, with earth curvature and refraction |
| 6 | `tools/osm_fetch.py`, `tools/osm_layers.py` | OpenStreetMap (Overpass) | road masks for the rings, place and peak labels |
| 7 | `unreal/mesh_terrain_place.py` | the imported Mesh Terrain | terrain at the survey height (UE Z 0 = real mid-height) |
| 8 | `unreal/place_trees.py` | `trees_<tag>.csv` | one instanced mesh per tree, snapped to the ground and checked |
| 9 | `unreal/horizon_mesh.py` | the rings + road masks | two Nanite horizon meshes, a road overlay, editor-only labels |

Steps 1–6 run outside the editor. Steps 7–9 run inside the Unreal Editor (Tools → Execute Python Script, the `py`
console command, or an agent over Epic's Unreal MCP server).

## Quick start

```sh
uv sync                                   # Python 3.10+; installs numpy, tifffile, pyproj, scipy, laspy[lazrs]
uv run tools/site_init.py --dtm DTM.tif --lat <lat> --lon <lon> --crs EPSG:3763 --size 1009 --label "My place"
uv run tools/heightmap.py --site site.json --dtm DTM.tif --dsm DSM.tif --out out/
uv run tools/laz_extract.py --terrain out/terrain.json --laz CLOUD.laz --out out/
uv run tools/horizon.py --terrain out/terrain.json --dem-dir copernicus/ --dtm DTM.tif --out out/
uv run tools/osm_fetch.py --terrain out/terrain.json --out out/
uv run tools/osm_layers.py --terrain out/terrain.json --near out/osm_near.json --major out/osm_major.json --out out/
```

`heightmap.py` prints the numbers for the import dialog. Then, in Unreal 5.8:

1. **Mesh Terrain** (experimental in 5.8; Agoro Camp uses it): Mesh Terrain mode → *Import Heightmap* →
   `heightmap_<n>.png` with the printed Size X/Y/Z. This is a click; 5.8 has no Python route to it.
   Then run `unreal/mesh_terrain_place.py`.
   **Or Landscape**: *Import from File* with the printed Scale X/Y/Z.
2. Copy `lidar-to-unreal.example.json` to `lidar-to-unreal.json` next to your `.uproject`, point `data_dir` at
   `out/`, and set your tree meshes.
3. Run `unreal/place_trees.py` (spawn, snap, check, save) and `unreal/horizon_mesh.py`.

Coordinates everywhere: UE (0, 0) is the centre of the survey window, **+X east, +Y south**, centimetres; UE Z 0 is the
window's mid-height (`terrain.json` → `z0_m`).

## Data sources and what you owe them

| Data | Where | Licence and credit you must show |
|---|---|---|
| Portugal 50 cm DTM/DSM and LiDAR point clouds, 25 cm orthophotos | Direção-Geral do Território, [cdd.dgterritorio.gov.pt](https://cdd.dgterritorio.gov.pt) (free registration) | CC BY 4.0: credit "Direção-Geral do Território" |
| Copernicus DEM GLO-30 | [Copernicus Data Space](https://dataspace.copernicus.eu) | © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA |
| Roads, places, peaks | [OpenStreetMap](https://www.openstreetmap.org) via the Overpass API | ODbL 1.0: "© OpenStreetMap contributors" |

The tools were built for Portugal's DGT data, but they only assume a north-up GeoTIFF in a metric CRS and an
ASPRS-classified point cloud, so other national LiDAR programmes should work. Please open an issue if yours doesn't.

## How I know it works

- **Regression against the game.** Run on the Agoro Camp survey tile, the tools reproduce the files the game was built
  from: heightmap, canopy, both orthophoto bands and the class map pixel for pixel, the tree, building and water CSVs
  byte for byte (3,000 trees), and the road masks and all 386 labels.
- **One deliberate difference:** the horizon. The game's original builder interpolated inside each Copernicus tile
  separately. That left a ridge up to 11 m along the 40° N tile seam in Agoro Camp's horizon. `horizon.py` now
  interpolates across tiles on their shared global grid. Everywhere except the seam cells, the output still equals
  the original.
- **Synthetic tests** (`uv run pytest`): known heights and import numbers, a refused nodata hole, a single cone tree
  found within 0.75 m of its trunk, and a seam test with a control (a 50 m step between tiles must be caught).
- **The editor scripts** are the ones Agoro Camp was built with, made configurable. In this general form they have not
  yet been re-run in a fresh project; if one breaks for you, open an issue.

[docs/unreal-notes.md](docs/unreal-notes.md) lists the Unreal 5.8 traps this pipeline ran into, Mesh Terrain especially.

## How this was made

I wrote this with AI coding agents (Claude Code) working alongside me. I direct the work, review it and am responsible
for every line. The Unreal Editor steps were first driven by agents through Epic's Unreal MCP server.

## Licence

Apache License 2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE). Contributions are welcome under the
[Developer Certificate of Origin](CONTRIBUTING.md). "Agoro Games", "Agoro Camp" and "Camp Afric" are names of
Sankofa Digital OÜ and are not licensed with this code. Data you download stays under its own licence (table above).
