"""Shared by the editor scripts: finds lidar-to-unreal.json and the data folder the tools/ step wrote.

lidar-to-unreal.json sits in your Unreal project folder (next to the .uproject), or set L2U_CONFIG to its path:
  {
    "data_dir": "path/to/out",                 absolute, or relative to the project folder
    "content_dir": "/Game/LidarToUnreal",      where generated assets go
    "trees":   {...},                          see place_trees.py
    "horizon": {...}                           see horizon_mesh.py
  }
"""
import json
import os

import unreal


def project_dir():
    return unreal.SystemLibrary.get_project_directory()


def config():
    path = os.environ.get("L2U_CONFIG") or os.path.join(project_dir(), "lidar-to-unreal.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    d = cfg.get("data_dir", "lidar-to-unreal-data")
    cfg["data_dir"] = d if os.path.isabs(d) else os.path.normpath(os.path.join(project_dir(), d))
    cfg.setdefault("content_dir", "/Game/LidarToUnreal")
    return cfg


def data(cfg, name):
    return os.path.join(cfg["data_dir"], name)


def terrain(cfg):
    with open(data(cfg, "terrain.json"), encoding="utf-8") as f:
        return json.load(f)


def steps(section, default):
    """Steps to run: env L2U_STEPS (comma list) beats the config's "<section>": {"steps": [...]}, beats the default."""
    env = os.environ.get("L2U_STEPS")
    if env:
        return [s.strip() for s in env.split(",") if s.strip()]
    return list(config().get(section, {}).get("steps", default))
