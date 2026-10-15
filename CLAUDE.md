# Claude Code entrypoint

## Concept image

```text
local-reference/class-c-concept.png
```

The private concept image (gitignored, contains third-party logos; copy it in by hand) shows the compact truck-based Class C camper with interior/rear views. It is inspiration, not measured geometry, and is never packaged into the mod.

Read README.md and docs/roadmap.md before implementation. The task is a Class C motorhome on a two-door, badge-free, heavy-duty (one-ton-style) regular-cab chassis cab with dual rear wheels for ATS Road Trip: Ford, split out of the bed-accessories repo because it needs its own chassis. It is a separate project with its own scope. Open Class C gates: `docs/compatibility.md`.

## Current state

- Preview renders only: `scripts/render_variants.py --variant class_c` on a reference HD chassis cab (`truck.source: hd_reference`): a CC BY 1999-2007-generation heavy-duty regular-cab pickup cut behind the cab, debadged, repainted, with DRW wheel assemblies from a CC BY-SA derived chassis-cab model (`scripts/extract_hd_wheels.py`), procedural frame/axle/springs, `wheelbase_cc` 4.19 (165 in). A render construct, not a measured chassis cab. The only fallback is the procedural chassis (`--set truck.source=procedural`).
- Because the wheel assemblies come from a CC BY-SA model, the preview renders are BY-SA adaptations (README Credits).
- Naming: use neutral terms in new code, config keys and docs ("HD chassis cab", `hd_chassis`, `hd_reference`); model titles appear only in the README credit lines.
- In game: original cab/chassis geometry from public body-builder dimensions; Road Trip's installed pickup is a 4-door crew cab and a cut-down SCS model cannot be shipped.
- Eevee shows glass/interiors wrongly bright with sorting artifacts; judge glass in Cycles. Check every view close up for leftover badges or lettering after any change to the reference chassis.

## Tools

`tools/` (gitignored) is this repo's own toolchain folder: portable Blender 3.6.23, the SCS add-on zip and the HDRI (`scripts/fetch_tools.ps1`), plus `reference-hd-chassis/` (README 'Tools'). Paths starting with `tools/` resolve through `scripts/lib/common.py` `tools_root()`: `ATS_TOOLS_DIR`, then `config/tools.local.json` `tools_dir`, else `./tools`. This repo shares nothing on disk with any other repo. Never commit `tools/`, `renders/`, `logs/` or `local-reference/`.

## Automation rules

Drive Blender 3.6.23 with Python in background command-line runs. Author deterministic scripts for geometry, materials, scene setup, rendering and validation; no reliance on interactive preferences or selection state. When an export pipeline is added, explicitly enable the SCS add-on in the background process, check operator availability against the pinned add-on and do not invent an SCS export API.

Use project-relative paths and configurable tool paths. Fail on missing inputs, unsupported versions, or export errors. Capture stdout/stderr, exit codes, tool versions, configuration and output hashes.

Render with Cycles (`surface-photo`) for anything judged visually, **one view per Blender process** on the Surface Pro (several views in one process have hit low-memory stops). Eevee `surface` is for quick framing checks only. Use the gaming PC for expensive renders and game validation.

The shared libraries in `scripts/lib/` are copies of the bed-accessories repo's; duplication is intentional. Keep the render look (config/render.json, materials, environment) consistent by hand when either changes.

## Scope and evidence

- Preserve installed drivetrain/interior/physics references when supported. Do not claim the Class C is cosmetic: wheelbase, overhang, frame, cameras, collision, suspension and physics all change.
- Use original geometry and permitted textures. Never include proprietary SCS or third-party dependency assets (including the reference models, the extracted wheel .blend or any cut-down SCS cab) in Git or release packages.
- Do not modify installed game archives. Use a separate test profile and reversible mod deployment.
- Keep implementation, conversion, rendering and in-game validation statuses separate. A render is not proof of a working mod.
- Record limitations and blocked gates; do not silently substitute a different vehicle or claim unsupported Road Trip behavior.
