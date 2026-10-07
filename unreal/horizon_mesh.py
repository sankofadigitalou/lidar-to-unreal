"""Horizon around the survey window: two Nanite meshes + a road overlay + editor-only place labels (run in the editor).

Inputs (from tools/): horizon_{near,far}.f32 + horizon.json (tools/horizon.py, Copernicus GLO-30) and
roads_{near,far}.png + labels.json (tools/osm_layers.py, OpenStreetMap), all in the data folder.
Steps (L2U_STEPS or lidar-to-unreal.json "horizon": {"steps": [...]}): material, near, far, labels, save.

Mesh = a GeometryScript rectangle grid whose vertices get the heights (append_buffers_to_mesh drew nothing in 5.8).
Material: altitude tint (lowland olive -> rock), road mask by world XY, scalar ShowRoads (0..1).
Labels are TextRender actors in Geo/Labels, hidden in game: they are for finding places in the editor.

"horizon" config: "rock_from_m" / "rock_full_m" (absolute altitudes of the tint ramp, default 1300 / 1900),
"hole" (default true), "near_fallback_percent" (default 0.25), "actors" (default true).

hole: delete the triangles entirely inside each ring's SUNK region, one grid step inside it, so the sunk band still meets
the finer surface. Without Nanite (SM5, e.g. Intel Iris Xe) a ring draws its fallback mesh (~1,500 triangles for +-6 km),
which interpolates straight across the sunk region and lies ABOVE the terrain as a flat brown plane. A hole cannot be
bridged by the simplifier; with Nanite the deleted triangles were metres under the finer surface, so nothing changes.
near_fallback_percent: the near ring's Nanite fallback keeps this % of its triangles (Auto kept ~0.5 %, ~430 m
triangles, which rose above the ground at the window edge on SM5). Hardware ray tracing traces the fallback too.
"""
import array, json, os
import unreal

import l2u_unreal as l2u

CFG = l2u.config()
HZ = CFG.get("horizon", {})
G = CFG["data_dir"]
DIR = CFG["content_dir"] + "/Horizon"
STEPS = l2u.steps("horizon", ["material", "near", "far", "labels", "save"])
HOLE = bool(HZ.get("hole", True))
ACTORS = bool(HZ.get("actors", True))
NEAR_FALLBACK = float(HZ.get("near_fallback_percent", 0.25))
meta = json.load(open(os.path.join(G, "horizon.json")))
Z0_M = float(meta["z0_m"])
ROCK_FROM_CM = (float(HZ.get("rock_from_m", 1300.0)) - Z0_M) * 100.0
ROCK_SPAN_CM = (float(HZ.get("rock_full_m", 1900.0)) - float(HZ.get("rock_from_m", 1300.0))) * 100.0
# sunk half-size of each ring (tools/horizon.py) minus one grid step
HOLE_HALF_M = {k: r["sink_half_m"] - r["step_m"] for k, r in meta["rings"].items()}
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
mel = unreal.MaterialEditingLibrary
at = unreal.AssetToolsHelpers.get_asset_tools()
L = unreal.GeometryScript_List


def labelled(label):
    return [a for a in eas.get_all_level_actors() if a.get_actor_label() == label]


def import_texture(png, name):
    path = DIR + "/" + name
    if not unreal.EditorAssetLibrary.does_asset_exist(path):
        t = unreal.AssetImportTask()
        for k, v in (("filename", os.path.join(G, png)), ("destination_path", DIR), ("destination_name", name),
                     ("automated", True), ("save", True)):
            t.set_editor_property(k, v)
        at.import_asset_tasks([t])
    tex = unreal.load_asset(path)
    tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_GRAYSCALE)
    tex.set_editor_property("srgb", False)
    tex.set_editor_property("address_x", unreal.TextureAddress.TA_CLAMP)
    tex.set_editor_property("address_y", unreal.TextureAddress.TA_CLAMP)
    unreal.EditorAssetLibrary.save_asset(path)
    return tex


def step_material():
    path = DIR + "/M_Horizon"
    mat = unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else \
        at.create_asset("M_Horizon", DIR, unreal.Material, unreal.MaterialFactoryNew())
    mel.delete_all_material_expressions(mat)
    E = lambda cls, x, y: mel.create_material_expression(mat, cls, x, y)
    wp = E(unreal.MaterialExpressionWorldPosition, -1600, 0)
    rg = E(unreal.MaterialExpressionComponentMask, -1400, -100); rg.set_editor_property("r", True); rg.set_editor_property("g", True)
    bz = E(unreal.MaterialExpressionComponentMask, -1400, 200); bz.set_editor_property("b", True)
    half = E(unreal.MaterialExpressionScalarParameter, -1400, -250); half.set_editor_property("parameter_name", "HalfCm"); half.set_editor_property("default_value", 600000.0)
    add = E(unreal.MaterialExpressionAdd, -1200, -150)
    two = E(unreal.MaterialExpressionMultiply, -1200, -300); two.set_editor_property("const_b", 2.0)
    div = E(unreal.MaterialExpressionDivide, -1000, -150)
    roads = E(unreal.MaterialExpressionTextureSampleParameter2D, -800, -150); roads.set_editor_property("parameter_name", "Roads")
    roads.set_editor_property("texture", unreal.load_asset(DIR + "/T_RoadsNear"))
    # A non-sRGB greyscale texture needs LINEAR_GRAYSCALE: with SAMPLERTYPE_GRAYSCALE the material failed to compile
    # for SF_METAL_SM6 (thousands of "Default Material will be used" lines) and both rings drew the default material.
    roads.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE)
    show = E(unreal.MaterialExpressionScalarParameter, -800, 50); show.set_editor_property("parameter_name", "ShowRoads"); show.set_editor_property("default_value", 1.0)
    rmask = E(unreal.MaterialExpressionMultiply, -600, -100)
    # altitude tint: rock from rock_from_m to rock_full_m (absolute altitudes; UE Z 0 = z0_m)
    zlerp = E(unreal.MaterialExpressionSubtract, -1200, 200); zlerp.set_editor_property("const_b", ROCK_FROM_CM)
    zdiv = E(unreal.MaterialExpressionDivide, -1000, 200); zdiv.set_editor_property("const_b", ROCK_SPAN_CM)
    zsat = E(unreal.MaterialExpressionSaturate, -850, 200)
    low = E(unreal.MaterialExpressionConstant3Vector, -850, 320); low.set_editor_property("constant", unreal.LinearColor(0.16, 0.17, 0.09, 1))
    rock = E(unreal.MaterialExpressionConstant3Vector, -850, 440); rock.set_editor_property("constant", unreal.LinearColor(0.32, 0.31, 0.28, 1))
    tint = E(unreal.MaterialExpressionLinearInterpolate, -600, 250)
    road_c = E(unreal.MaterialExpressionConstant3Vector, -600, 450); road_c.set_editor_property("constant", unreal.LinearColor(0.55, 0.50, 0.42, 1))
    base = E(unreal.MaterialExpressionLinearInterpolate, -350, 100)
    rough = E(unreal.MaterialExpressionConstant, -350, 300); rough.set_editor_property("r", 0.95)
    c = mel.connect_material_expressions
    c(wp, "", rg, ""); c(wp, "", bz, "")
    c(rg, "", add, "A"); c(half, "", add, "B"); c(half, "", two, "A"); c(add, "", div, "A"); c(two, "", div, "B")
    c(div, "", roads, "UVs"); c(roads, "", rmask, "A"); c(show, "", rmask, "B")
    c(bz, "", zlerp, "A"); c(zlerp, "", zdiv, "A"); c(zdiv, "", zsat, "")
    c(low, "", tint, "A"); c(rock, "", tint, "B"); c(zsat, "", tint, "Alpha")
    c(tint, "", base, "A"); c(road_c, "", base, "B"); c(rmask, "", base, "Alpha")
    mel.connect_material_property(base, "", unreal.MaterialProperty.MP_BASE_COLOR)
    mel.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    try:                                           # the rings are Nanite meshes; a cooked game does not set usage flags
        mat.set_editor_property("used_with_nanite", True)
    except Exception as e:
        unreal.log_warning("horizon: used_with_nanite not settable here: %s" % e)
    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_asset(path)
    for ring, tex in (("Near", "T_RoadsNear"), ("Far", "T_RoadsFar")):
        mi_path = DIR + "/MI_Horizon" + ring
        mi = unreal.load_asset(mi_path) if unreal.EditorAssetLibrary.does_asset_exist(mi_path) else \
            at.create_asset("MI_Horizon" + ring, DIR, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        mel.set_material_instance_parent(mi, mat)
        mel.set_material_instance_scalar_parameter_value(mi, "HalfCm", meta["rings"][ring.lower()]["half_m"] * 100.0)
        mel.set_material_instance_texture_parameter_value(mi, "Roads", unreal.load_asset(DIR + "/" + tex))
        unreal.EditorAssetLibrary.save_asset(mi_path)
    unreal.log("horizon: material + instances")


def build_ring(ring):
    r = meta["rings"][ring]; n, half = r["n"], r["half_m"] * 100.0
    z = array.array("f"); z.frombytes(open(os.path.join(G, "horizon_%s.f32" % ring), "rb").read())
    assert len(z) == n * n, (len(z), n)
    dm = unreal.DynamicMesh()
    unreal.GeometryScript_Primitives.append_rectangle_xy(dm, unreal.GeometryScriptPrimitiveOptions(), unreal.Transform(),
                                                        2 * half, 2 * half, n, n)          # 5.8: steps = VERTICES per side
    pos = list(L.convert_vector_list_to_array(unreal.GeometryScript_MeshQueries.get_all_vertex_positions(dm, False)[1]))
    step = 2 * half / (n - 1)
    new = []
    for v in pos:
        i = min(n - 1, max(0, int(round((v.x + half) / step)))); j = min(n - 1, max(0, int(round((v.y + half) / step))))
        new.append(unreal.Vector(v.x, v.y, z[j * n + i]))
    unreal.GeometryScript_MeshEdits.set_all_mesh_vertex_positions(dm, L.convert_array_to_vector_list(new))
    if HOLE:
        h = HOLE_HALF_M[ring] * 100.0
        box = unreal.Box(min=unreal.Vector(-h, -h, -1.0e8), max=unreal.Vector(h, h, 1.0e8))
        sel = unreal.GeometryScript_MeshSelection.select_mesh_elements_in_box(
            dm, box, unreal.GeometryScriptMeshSelectionType.TRIANGLES, False, 3)
        sel = sel[1] if isinstance(sel, tuple) else sel
        res = unreal.GeometryScript_MeshEdits.delete_selected_triangles_from_mesh(dm, sel)
        unreal.log("horizon: %s hole +-%.0f m, %s triangles deleted" % (ring, HOLE_HALF_M[ring], res[1] if isinstance(res, tuple) else res))
    unreal.GeometryScript_Normals.recompute_normals(dm, unreal.GeometryScriptCalculateNormalsOptions())
    path = "%s/SM_Horizon%s" % (DIR, ring.capitalize())
    if unreal.EditorAssetLibrary.does_asset_exist(path):          # never delete a referenced mesh (segfault): write into it
        sm = unreal.load_asset(path)
        o = unreal.GeometryScriptCopyMeshToAssetOptions()
        o.set_editor_property("enable_recompute_normals", False); o.set_editor_property("replace_materials", False)
        unreal.GeometryScript_AssetUtils.copy_mesh_to_static_mesh(dm, sm, o, unreal.GeometryScriptMeshWriteLOD())
    else:
        o = unreal.GeometryScriptCreateNewStaticMeshAssetOptions()
        o.set_editor_property("enable_recompute_normals", False); o.set_editor_property("enable_collision", False)
        res = unreal.GeometryScript_NewAssetUtils.create_new_static_mesh_asset_from_mesh(dm, path, o)
        sm = res[0] if isinstance(res, tuple) else res
    ns = sm.get_editor_property("nanite_settings"); ns.enabled = True
    if ring == "near" and NEAR_FALLBACK > 0:
        ns.fallback_target = unreal.NaniteFallbackTarget.PERCENT_TRIANGLES; ns.fallback_percent_triangles = NEAR_FALLBACK
    sm.set_editor_property("nanite_settings", ns)
    sm.set_material(0, unreal.load_asset("%s/MI_Horizon%s" % (DIR, ring.capitalize())))
    unreal.EditorAssetLibrary.save_loaded_asset(sm)
    unreal.log("horizon: %s LOD0 (fallback on this RHI) %d triangles" % (ring, sm.get_num_triangles(0)))
    if not ACTORS:
        return
    label = "Horizon_" + ring.capitalize()
    for a in labelled(label):
        eas.destroy_actor(a)
    a = eas.spawn_actor_from_object(sm, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
    a.set_actor_label(label); a.set_folder_path("Horizon")
    a.set_editor_property("is_spatially_loaded", False)           # always loaded: it IS the skyline
    smc = a.static_mesh_component
    smc.set_editor_property("cast_shadow", ring == "near")
    # no collision: it would come from Nanite's simplified fallback mesh (metres off), and every ground check traces
    smc.set_collision_profile_name("NoCollision")
    unreal.log("horizon: %s %dx%d vertices, z %.0f..%.0f cm" % (label, n, n, min(z), max(z)))


def step_labels():
    for a in [x for x in eas.get_all_level_actors() if x.get_folder_path() == "Geo/Labels"]:
        eas.destroy_actor(a)
    near_z = array.array("f"); near_z.frombytes(open(os.path.join(G, "horizon_near.f32"), "rb").read())
    far_z = array.array("f"); far_z.frombytes(open(os.path.join(G, "horizon_far.f32"), "rb").read())
    def ground(x, y):
        for ring, zs in (("near", near_z), ("far", far_z)):
            r = meta["rings"][ring]; n, half = r["n"], r["half_m"] * 100.0; step = 2 * half / (n - 1)
            if abs(x) < half and abs(y) < half:
                return zs[int(round((y + half) / step)) * n + int(round((x + half) / step))]
        return 0.0
    size = {"site": 800.0, "city": 6000.0, "town": 3500.0, "village": 1200.0, "peak": 3000.0}
    count = 0
    for lb in json.load(open(os.path.join(G, "labels.json"))):
        x, y = float(lb["x"]), float(lb["y"])
        if abs(x) > 5000000 or abs(y) > 5000000:
            continue
        z = ground(x, y) + size[lb["kind"]] * 1.5
        a = eas.spawn_actor_from_class(unreal.TextRenderActor, unreal.Vector(x, y, z), unreal.Rotator(0, 0, 90))
        a.set_actor_label("Label_" + lb["name"]); a.set_folder_path("Geo/Labels")
        t = a.text_render
        t.set_editor_property("text", unreal.Text(lb["name"] + (" %d m" % lb["ele"] if lb["kind"] == "peak" and lb["ele"] else "")))
        t.set_editor_property("world_size", size[lb["kind"]])
        t.set_editor_property("horizontal_alignment", unreal.HorizTextAligment.EHTA_CENTER)
        a.set_actor_hidden_in_game(True)
        a.set_editor_property("is_spatially_loaded", False)
        count += 1
    unreal.log("horizon: %d labels (editor only, hidden in game)" % count)


def step_save():
    unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()


if "material" in STEPS:
    import_texture("roads_near.png", "T_RoadsNear"); import_texture("roads_far.png", "T_RoadsFar")
for s in STEPS:
    {"material": step_material, "near": lambda: build_ring("near"), "far": lambda: build_ring("far"),
     "labels": step_labels, "save": step_save}[s.strip()]()
