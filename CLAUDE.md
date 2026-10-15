# Claude Code entrypoint

## Concept image

```text
local-reference/f150-camper-concept.png
```

The private concept image (gitignored, contains third-party logos; copy it in by hand, same file as in the camper repo) shows the compact truck-based Class C camper with interior/rear views. It is inspiration, not measured geometry, and is never packaged into the mod.

Read README.md and docs/roadmap.md before implementation. The task is an F-150-cab-based Class C motorhome for ATS Road Trip: Ford, split out of the bed-accessory repo `ats-f150-camper` (sibling folder) because it needs its own chassis. Treat it as a separate major scope from the camper's V1 shell.

## Current state

- Preview renders only: `scripts/render_variants.py --variant class_c` on a reference cab-chassis (the CC BY crew-cab model cut behind the cab, procedural frame, duals at `wheelbase_cc` 5.3). That is a render construct, not a real or measured chassis cab.
- Open: 2-door regular cab. Road Trip only ships the 4-door `pckup4d_55` cabin; a cut-down SCS model cannot be shipped, so in game it is either the crew cab or an original cab/chassis of our own.
- Eevee shows glass/interiors wrongly bright with sorting artifacts; judge glass in Cycles.

## Tools

`tools/` is not in this repo. Paths starting with `tools/` resolve through `scripts/lib/common.py` `tools_root()`: `ATS_TOOLS_DIR`, then `config/tools.local.json` `tools_dir`, then a local `./tools` (folder or junction), then `../ats-f150-camper/tools`. Never commit `tools/`, `renders/`, `logs/` or `local-reference/`.

## Automation rules

Drive Blender 3.6.23 with Python in background command-line runs. Author deterministic scripts for geometry, materials, scene setup, rendering and validation; no reliance on interactive preferences or selection state. When an export pipeline is added, explicitly enable the SCS add-on in the background process, check operator availability against the pinned add-on and do not invent an SCS export API.

Use project-relative paths and configurable tool paths. Fail on missing inputs, unsupported versions, or export errors. Capture stdout/stderr, exit codes, tool versions, configuration and output hashes.

Render with Cycles (`surface-photo`) for anything judged visually, **one view per Blender process** on the Surface Pro (several views in one process have hit low-memory stops). Eevee `surface` is for quick framing checks only. Use the gaming PC for expensive renders and game validation.

The shared libraries in `scripts/lib/` are copies of the camper repo's; duplication is intentional. Keep the render look (config/render.json, materials, environment) consistent with the camper repo when either changes.

## Scope and evidence

- Preserve installed drivetrain/interior/physics references when supported. Do not claim the Class C is cosmetic: wheelbase, overhang, frame, cameras, collision, suspension and physics all change.
- Use original geometry and permitted textures. Never include proprietary SCS or third-party dependency assets (including the reference truck or any cut-down SCS cab) in Git or release packages.
- Do not modify installed game archives. Use a separate test profile and reversible mod deployment.
- Keep implementation, conversion, rendering and in-game validation statuses separate. A render is not proof of a working mod.
- Record limitations and blocked gates; do not silently substitute a different vehicle or claim unsupported Road Trip behavior.
