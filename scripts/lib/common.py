"""Shared helpers for pipeline scripts.

Stdlib only: imported both by plain Python (preflight, package, deploy) and by
Blender's bundled Python (build_scene, export_scs, render_preview).
"""
import argparse
import datetime
import hashlib
import json
import os
import platform
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = REPO_ROOT / "logs"


class PipelineError(RuntimeError):
    """Raised for any condition that must stop the pipeline."""


def script_args(argv=None):
    """Return the arguments after '--' (Blender convention) or all args when run by plain Python."""
    argv = sys.argv if argv is None else argv
    if "--" in argv:
        return argv[argv.index("--") + 1:]
    return argv[1:]


def make_parser(description):
    return argparse.ArgumentParser(description=description)


DEFAULT_TOOLS_DIR = "../ats-f150-camper/tools"   # sibling camper repo; nothing is copied here


def tools_root():
    """Directory that repo paths starting with 'tools/' resolve to.

    Order: env ATS_TOOLS_DIR, then "tools_dir" in config/tools.local.json (gitignored), then a local
    tools/ folder or directory junction in this repo, then the sibling repo's tools/ (DEFAULT_TOOLS_DIR).
    Relative values resolve from this repo's root.
    """
    env = os.environ.get("ATS_TOOLS_DIR")
    if env:
        return (REPO_ROOT / env).resolve()
    cfg = REPO_ROOT / "config" / "tools.local.json"
    if cfg.is_file():
        with open(cfg, encoding="utf-8") as f:
            td = json.load(f).get("tools_dir")
        if td:
            return (REPO_ROOT / td).resolve()
    if (REPO_ROOT / "tools").exists():
        return REPO_ROOT / "tools"
    return (REPO_ROOT / DEFAULT_TOOLS_DIR).resolve()


def repo_path(p):
    """Resolve a repo-relative or absolute path; 'tools/...' goes through tools_root()."""
    p = Path(p)
    if p.is_absolute():
        return p
    if p.parts and p.parts[0] == "tools":
        return tools_root().joinpath(*p.parts[1:])
    return REPO_ROOT / p


def load_json(path):
    path = repo_path(path)
    if not path.is_file():
        raise PipelineError(f"missing input: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def sha256_json(obj):
    data = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def inventory(root):
    """Sorted list of {path, size, sha256} for every file under root."""
    root = Path(root)
    items = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            items.append({
                "path": p.relative_to(root).as_posix(),
                "size": p.stat().st_size,
                "sha256": sha256_file(p),
            })
    return items


def write_run_record(step, record):
    """Append evidence for one pipeline step to logs/<step>-<timestamp>.json."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    record = dict(record)
    record.setdefault("step", step)
    record.setdefault("timestamp", stamp)
    record.setdefault("host", platform.node())
    record.setdefault("python", sys.version.split()[0])
    out = LOG_DIR / f"{step}-{stamp}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True)
    return out


def ensure_inside(path, root):
    """Refuse to write outside an expected directory (protects shared tool/game dirs)."""
    path = Path(path).resolve()
    root = Path(root).resolve()
    if os.path.commonpath([path, root]) != str(root):
        raise PipelineError(f"refusing to touch {path}: outside {root}")
    return path


def run_main(main):
    """Run main(), convert PipelineError into exit code 1 with a clear message."""
    try:
        main()
    except PipelineError as e:
        print(f"PIPELINE ERROR: {e}", file=sys.stderr)
        sys.exit(1)
