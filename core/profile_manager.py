import json, os
from copy import deepcopy

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_DIR = os.path.join(BASE_DIR, "profiles")

def _deep_merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def load_profile(name: str | None):
    name = (name or "default").strip().lower()

    default_path = os.path.join(PROFILES_DIR, "default.json")
    with open(default_path, "r", encoding="utf-8") as f:
        default_prof = json.load(f)

    path = os.path.join(PROFILES_DIR, f"{name}.json")
    if not os.path.exists(path):
        return default_prof

    with open(path, "r", encoding="utf-8") as f:
        prof = json.load(f)

    parent = prof.get("inherits")
    if parent:
        parent_path = os.path.join(PROFILES_DIR, f"{parent}.json")
        with open(parent_path, "r", encoding="utf-8") as pf:
            parent_prof = json.load(pf)
        prof = _deep_merge(parent_prof, prof)

    # Siempre merge sobre default
    return _deep_merge(default_prof, prof)
