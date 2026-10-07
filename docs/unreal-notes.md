# Unreal Engine 5.8 notes: what this pipeline tripped over

Each of these cost time while building Agoro Camp. They were all observed in UE 5.8 on macOS (Apple Silicon), with some
on Windows; check them again on later versions.

## Mesh Terrain (experimental in 5.8)

- **Import Heightmap is a GUI click.** There is no Python route to it in 5.8. Use the sizes `heightmap.py` prints;
  Size Z must equal the real height range in cm, or the heights stretch.
- **The MeshPartition actor has zero bounds.** The geometry lives in the `Section_X*-Y*` actors, and their component
  bounds carry a padded floor. Read the DynamicMesh vertex bounds if you need the real extent.
- **No collision in the editor.** The render mesh is a DynamicMeshComponent with NoCollision, so line traces (for
  example `place_trees.py snap`) miss until you add collision proxies built from the render sections.
- **`-game` cannot load a Mesh Terrain level uncooked:** `Assertion failed: ComponentNativeClass`
  (WorldPartitionActorDesc.cpp). The modifiers are editor-only and a cook strips them. Build the compiled sections with
  the `WorldPartitionMeshPartitionBuilder` commandlet and measure performance in a cooked build.
- **Material:** the terrain ignores the section components' material slots. Its material comes from the
  `MeshPartitionDefinition` (default `/MeshPartition/DataAssets/MPD_Default`); duplicate it into `/Game` and project
  textures by world XY.
- **A LakeModifier added from Python is bound to no terrain** and changes nothing. Bind it:
  `mod.call_method("BP_SetAffectedMegaMesh", (mesh_partition,))`.

## Python in the editor

- `Actor.add_component_by_class` is not exposed to Python; use the SubobjectDataSubsystem (see `place_trees.py`).
- `SystemLibrary.line_trace_single` returns `None` on a miss, not a hit result with `blocking_hit = False`.
- `GeometryScript_Primitives.append_rectangle_xy`: the step counts are **vertices** per side, not quads.
- A non-sRGB greyscale texture needs `SAMPLERTYPE_LINEAR_GRAYSCALE` in a material sampler. With `SAMPLERTYPE_GRAYSCALE` the
  material failed to compile for Metal SM6, and every mesh using it drew the default material.
- **World Partition loads nothing after an editor restart** (no loaded region): terrain, trees and horizon seem to
  vanish. Load the region again before you judge anything.
- If you pass settings to editor scripts through environment variables, scope them to one call: the editor's Python is
  long-lived and `os.environ` changes leak into every later script.

## Performance

- **Tree wind:** with world-position-offset at every distance, virtual shadow maps redraw every swaying tree's shadow
  every frame (3,000 trees: 62–67 ms GPU facing the tree band). `place_trees.py` limits wind to 50 m from the camera.
- **Trees as one always-loaded actor:** as a World Partition streamed actor the trees popped in seconds after start.
- **Nanite fallbacks on low-end GPUs (SM5, e.g. Intel Iris Xe on D3D11):** a Nanite mesh draws its fallback mesh there.
  The ±6 km horizon ring's automatic fallback had ~1,500 triangles and lay *above* the camp as a flat brown plane, which
  is why `horizon_mesh.py` cuts a hole under the finer surface and keeps 0.25 % of the near ring's triangles. A
  tree's fallback has ONE LOD by default: 3,000 trees × ~12,000 triangles was 36.7 M triangles per frame on SM5.
- Horizon meshes get **no collision**: Nanite fallback collision is metres off and every ground check would hit it.
