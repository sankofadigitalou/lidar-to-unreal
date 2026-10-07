"""Place every LiDAR tree at its real position as instanced meshes (instance k of a species = its k-th CSV row).

Run in the editor, in order:
    spawn   before or after the terrain exists (Z from the CSV)
    snap    after the terrain exists: each trunk base is line-traced onto the ground
    check   writes trees_check.json to the data folder: count, XY error, how many bases sit within 50 cm
    save
Steps come from L2U_STEPS or lidar-to-unreal.json "trees": {"steps": [...]} (default spawn, check).

Config ("trees" in lidar-to-unreal.json):
  "csv":      "trees_<tag>.csv" (default from terrain.json's tag)
  "species":  a FIRST-MATCH list; each rule may set min_height_m, max_height_m, max_crown_ratio (crown radius /
              height); the last rule should have no conditions. Example:
                [{"name": "Pine", "mesh": "/Game/Trees/SM_Pine", "min_height_m": 8, "max_crown_ratio": 0.35},
                 {"name": "Oak",  "mesh": "/Game/Trees/SM_Oak"}]
              Meshes need their pivot at the trunk base. Height scales Z, crown radius scales X/Y.
  "wind_cm":  world-position-offset (wind) only within this distance of the camera; 0 = no wind. Default 5000.
              With wind at every distance, virtual shadow maps redraw every swaying tree's shadow each frame: on the
              project this came from, 3,000 trees cost 62-67 ms of GPU facing the tree band.
"""
import json
import os
import random

import unreal

import l2u_unreal as l2u

cfg = l2u.config()
tcfg = cfg.get("trees", {})
CSV = l2u.data(cfg, tcfg.get("csv", "trees_%s.csv" % l2u.terrain(cfg).get("tag", "site")))
RULES = tcfg.get("species")
if not RULES:
    raise RuntimeError('set "trees": {"species": [...]} in lidar-to-unreal.json (see this script\'s docstring)')
LABEL = tcfg.get("label", "LidarTrees")
WIND_CM = int(tcfg.get("wind_cm", 5000))

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
with open(CSV, encoding="utf-8") as f:
    import csv
    rows = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(f)]


def species(r):
    for rule in RULES:
        h, ratio = r["height_m"], r["crown_r_m"] / max(r["height_m"], 1e-6)
        if h < rule.get("min_height_m", -1e9) or h > rule.get("max_height_m", 1e9) or ratio > rule.get("max_crown_ratio", 1e9):
            continue
        return rule["name"]
    raise RuntimeError("no species rule matches a %.1f m tree: give the last rule no conditions" % r["height_m"])


MESH = {rule["name"]: rule["mesh"] for rule in RULES}
GROUPS = {}
for i, r in enumerate(rows):
    GROUPS.setdefault(species(r), []).append(i)


def tree_actor():
    for a in eas.get_all_level_actors():
        if a.get_actor_label() == LABEL:
            return a
    return None


def components(actor):
    """{species: HISM}; components are named Trees_<species>."""
    return {c.get_name().replace("Trees_", ""): c
            for c in actor.get_components_by_class(unreal.HierarchicalInstancedStaticMeshComponent)}


def add_instance_component(actor, cls, name):
    """Actor.add_component_by_class is not exposed to Python in 5.8; the Subobject Data subsystem is."""
    sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    root = sds.k2_gather_subobject_data_for_instance(actor)[0]
    params = unreal.AddNewSubobjectParams()
    params.set_editor_property("parent_handle", root)
    params.set_editor_property("new_class", cls)
    handle, fail = sds.add_new_subobject(params)
    if fail and str(fail):
        raise RuntimeError("add_new_subobject: %s" % fail)
    sds.rename_subobject(handle, unreal.Text(name))
    return unreal.SubobjectDataBlueprintFunctionLibrary.get_object(sds.k2_find_subobject_data_from_handle(handle))


def transforms(mesh, idx, zs):
    b = mesh.get_bounding_box()
    mesh_h = b.max.z                                   # pivot at the trunk base: height above it
    mesh_r = (b.max.x - b.min.x + b.max.y - b.min.y) / 4.0
    rng = random.Random(7)
    out = []
    for i in idx:
        r = rows[i]
        s_xy = r["crown_r_m"] * 100.0 / mesh_r
        out.append(unreal.Transform(unreal.Vector(r["ue_x_cm"], r["ue_y_cm"], zs[i]),
                                    unreal.Rotator(0.0, 0.0, rng.uniform(0, 360)),     # (roll, pitch, yaw)
                                    unreal.Vector(s_xy, s_xy, r["height_m"] * 100.0 / mesh_h)))
    return out


def fill(actor, zs):
    for name, comp in components(actor).items():
        comp.clear_instances()
        comp.add_instances(transforms(comp.get_editor_property("static_mesh"), GROUPS.get(name, []), zs), False, True)


def step_wind():
    for name, comp in components(tree_actor()).items():
        comp.set_editor_property("evaluate_world_position_offset", WIND_CM > 0)
        comp.set_editor_property("world_position_offset_disable_distance", max(0, WIND_CM))


def step_spawn():
    old = tree_actor()
    if old:
        eas.destroy_actor(old)
    actor = eas.spawn_actor_from_class(unreal.Actor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
    actor.set_actor_label(LABEL)
    actor.set_folder_path("Vegetation")
    # always loaded: as a World Partition streamed actor the trees popped in seconds after the game started
    actor.set_editor_property("is_spatially_loaded", False)
    for name in GROUPS:
        comp = add_instance_component(actor, unreal.HierarchicalInstancedStaticMeshComponent, "Trees_" + name)
        comp.set_static_mesh(unreal.load_asset(MESH[name]))
        comp.set_editor_property("mobility", unreal.ComponentMobility.STATIC)
    step_wind()
    fill(actor, [r["ue_z_cm"] for r in rows])
    unreal.log("trees: spawned %s" % {n: c.get_instance_count() for n, c in components(actor).items()})


def trace_ground(x, y, ignore):
    hit = unreal.SystemLibrary.line_trace_single(world, unreal.Vector(x, y, 1.0e6), unreal.Vector(x, y, -1.0e6),
                                                 unreal.TraceTypeQuery.ECC_VISIBILITY, True, ignore,
                                                 unreal.DrawDebugTrace.NONE, True)
    if hit is None:                                    # 5.8 returns None when nothing was hit
        return None
    t = hit.to_tuple()
    return t[4].z if t[0] else None


def step_snap():
    actor = tree_actor()
    zs, misses = [], 0
    for r in rows:
        z = trace_ground(r["ue_x_cm"], r["ue_y_cm"], [actor])
        if z is None:
            misses += 1
            z = r["ue_z_cm"]
        zs.append(z)
    fill(actor, zs)
    unreal.log("trees: snapped %d instances (%d traces missed and kept the CSV z). A Mesh Terrain has no collision in "
               "the editor: give it collision proxies first, or every trace misses." % (len(zs), misses))


def step_check():
    actor = tree_actor()
    comps = components(actor)
    n = sum(c.get_instance_count() for c in comps.values())
    rng = random.Random(2026)
    worst_xy = 0.0
    for i in rng.sample(range(len(rows)), min(20, len(rows))):
        name = species(rows[i])
        loc = comps[name].get_instance_transform(GROUPS[name].index(i), True).translation
        worst_xy = max(worst_xy, ((loc.x - rows[i]["ue_x_cm"]) ** 2 + (loc.y - rows[i]["ue_y_cm"]) ** 2) ** 0.5)
    dz, missed = [], 0
    for r in rows:
        z = trace_ground(r["ue_x_cm"], r["ue_y_cm"], [actor])
        if z is None:
            missed += 1
        else:
            dz.append(z - r["ue_z_cm"])
    within = sum(1 for d in dz if abs(d) <= 50.0)
    res = {"instances": n, "csv_rows": len(rows), "per_species": {k: c.get_instance_count() for k, c in comps.items()},
           "sample20_worst_xy_cm": round(worst_xy, 4), "terrain_traced": len(dz), "trace_missed": missed,
           "base_z_within_50cm": within, "pct_within_50cm": round(100.0 * within / max(1, len(rows)), 2),
           "median_abs_dz_cm": round(sorted(abs(d) for d in dz)[len(dz) // 2], 2) if dz else None,
           "pass": n == len(rows) and worst_xy <= 1.0 and within >= 0.95 * len(rows)}
    with open(l2u.data(cfg, "trees_check.json"), "w") as f:
        json.dump(res, f, indent=1)
    unreal.log("trees check: %s" % json.dumps(res))


def step_save():
    unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()


for s in l2u.steps("trees", ["spawn", "check"]):
    {"spawn": step_spawn, "snap": step_snap, "check": step_check, "wind": step_wind, "save": step_save}[s]()
