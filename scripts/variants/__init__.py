"""Camper variant registry (render framework; see docs/variants.md).

A variant module is scripts/variants/<module>.py exposing

    def build(cfg, collection, mats) -> list[bpy.types.Object]

    cfg        - the variant config (config/variants/<name>.json) as a dict, plus
                 cfg["truck_info"]: lib.proxy_truck.TruckInfo facts in the variant frame
                 (no objects), and cfg["camper"]: the module's own parameters.
    collection - bpy collection to link every created object into.
    mats       - lib.materials.MaterialLibrary; mats["paint"] is the colour-matched body paint.

Optional module attributes: TRUCK_TYPES = ("pickup",) / ("cab_chassis",) / both (validated),
DESCRIPTION = "one line".

Modules are found by file name (variants.<module>), or registered explicitly with
@register("name") when one file provides several builders.
"""
import importlib
import pkgutil
from pathlib import Path

_REGISTRY = {}


def register(name, truck_types=("pickup", "cab_chassis")):
    """Decorator: register a build function under `name` (alternative to one module per name)."""
    def deco(fn):
        _REGISTRY[name] = (fn, tuple(truck_types))
        return fn
    return deco


def available():
    here = Path(__file__).resolve().parent
    mods = {m.name for m in pkgutil.iter_modules([str(here)]) if not m.name.startswith("_")}
    return sorted(mods | set(_REGISTRY))


def get(name):
    """Return (build, truck_types) for a module/registered name."""
    if name not in _REGISTRY:
        try:
            mod = importlib.import_module(f"variants.{name}")
        except ModuleNotFoundError as e:
            raise KeyError(f"no camper module '{name}' (available: {', '.join(available())})") from e
        if name not in _REGISTRY:
            build = getattr(mod, "build", None)
            if not callable(build):
                raise KeyError(f"variants/{name}.py has no build(cfg, collection, mats)")
            _REGISTRY[name] = (build, tuple(getattr(mod, "TRUCK_TYPES", ("pickup", "cab_chassis"))))
    return _REGISTRY[name]
