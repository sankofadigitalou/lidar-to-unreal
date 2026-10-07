"""Put an imported Mesh Terrain at the survey height (idempotent; run in the editor).

Before: Mesh Terrain mode > Import Heightmap with heightmap_<n>.png and the sizes tools/heightmap.py printed
(terrain.json "mesh_terrain"). In 5.8 that import is a click; there is no Python route to it.

Import Heightmap maps the 16-bit range to 0..Size Z and centres X/Y on the actor. Moving the actor to Z = -Size Z / 2
puts real altitude z0_m (terrain.json) at UE Z 0, the convention every other script here uses.
"""
import unreal

import l2u_unreal as l2u

cfg = l2u.config()
t = l2u.terrain(cfg)
z = float(t["mesh_terrain"]["actor_z_cm"])
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
mps = [a for a in eas.get_all_level_actors() if a.get_class().get_name() == "MeshPartition"]
if len(mps) != 1:
    raise RuntimeError("expected one Mesh Terrain (MeshPartition) actor in the level, found %d" % len(mps))
mp = mps[0]
mp.set_actor_label(cfg.get("terrain_label", "MeshTerrain_" + t.get("tag", "site")))
mp.set_actor_location(unreal.Vector(0.0, 0.0, z), False, False)
unreal.log("mesh terrain: actor Z %.1f cm, so UE Z 0 = %.2f m real altitude. Its geometry lives in the Section_X*-Y* "
           "actors; the MeshPartition actor itself reports zero bounds." % (z, t["z0_m"]))
