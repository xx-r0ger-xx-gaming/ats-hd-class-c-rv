# ATS Road Trip — Class C Motorhome on a Super Duty-Style Chassis Cab

A compact Class C motorhome (cabover berth, rear habitation body, dual rear wheels) built on a two-door, badge-free, Super Duty-style chassis cab. Target game: American Truck Simulator - Road Trip: Ford. Split out of [ats-f150-camper](https://github.com/xx-r0ger-xx-gaming/ats-f150-camper) on October 15, 2026, because a Class C eventually needs its own chassis rather than a truck-bed accessory slot.

Start with [CLAUDE.md](CLAUDE.md), then [the roadmap](docs/roadmap.md). Open gates: [docs/compatibility.md](docs/compatibility.md).

## Status

**Preview renders only.** Nothing here is exported, converted, packaged or tested in game, and a render is not proof that a mod works. Current state:

- **Stand-in:** the current preview uses a crew-cab F-150 model as a stand-in until the Super Duty reference is in. It is not the final chassis.
- The coach is original, render-only geometry (`scripts/variants/class_c.py`).
- The base vehicle in the renders is a **reference cab-chassis**: the downloaded crew-cab pickup model (see Credits) cut 12 mm behind the cab, cut openings capped, plus a procedural C-channel frame, crossmembers, rear axle, springs and dual rear wheels copied from the model's own wheel. It is a render construct, **not a real chassis cab** and not a measured one. `wheelbase_cc` is 5.3 m so the rear overhang matches the procedural regular-cab layout.
- **Open question: 2-door regular cab.** The intended look is a short 2-door cab, but Road Trip only ships the 4-door crew cab (cabin `pckup4d_55.ford.f150_23.cabin`, chassis `4d55_awd`). We cannot ship a cut-down or modified SCS model. In game this means either keeping the crew cab (long, but uses the installed vehicle) or building our own original cab and chassis (a much larger scope). Undecided; see the roadmap.
- **Eevee glass artifacts:** the `surface` (Eevee) profile shows the coach windows and interiors much brighter than Cycles and has glass sorting artifacts. Judge glass and windows in Cycles (`surface-photo` or `gaming`).

## Tools

This repo does not carry the multi-gigabyte `tools/` folder (portable Blender 3.6.23, the HDRI, the reference truck). Any repo path starting with `tools/` resolves, in order, to:

1. `ATS_TOOLS_DIR` environment variable (absolute, or relative to this repo's root);
2. `"tools_dir"` in `config/tools.local.json` (gitignored; copy `config/tools.example.json`);
3. `./tools` in this repo, if it exists (a real folder or a directory junction);
4. default: the sibling camper repo's tools, `../ats-f150-camper/tools`.

With both repos cloned side by side under one folder, nothing needs configuring. To use a junction instead (Windows, no admin rights needed):

```powershell
cmd /c mklink /J tools ..\ats-f150-camper\tools
```

Populate the tools with the camper repo's `scripts/fetch_tools.ps1` (Blender, HDRI; sha256-checked) and download the reference truck by hand as described there (`docs/gaming-pc-setup.md`, "Reference truck for preview renders").

## Rendering

```bash
B=../ats-f150-camper/tools/blender-3.6.23-windows-x64/blender.exe
# Cycles CPU, one view per Blender process (the Surface Pro has stopped on low memory with several)
for v in rear34 side front34; do
  $B --background --factory-startup --python-exit-code 1 --python scripts/render_variants.py -- \
     --variant class_c --profile surface-photo --views $v --no-sheet
done
# (drop --no-sheet on the last run to rebuild renders/variants/contact_sheet.png)
# bare base vehicles
$B ... -- --variant _ref_cab_chassis --set truck.source=reference --suffix _reference
```

Outputs go to `renders/variants/<name>_<view>.png` (gitignored), run evidence to `logs/render_variants-<timestamp>.json` (settings, camera, sun, seconds, output sha256). `--set key.path=value` overrides config keys (e.g. `--set truck.source=procedural` renders on the procedural regular-cab chassis), `--suffix` renames the outputs. Profiles and views are in `config/render.json`: `surface` (Eevee 1280x720, 32 samples), `surface-photo` (Cycles CPU, 192 adaptive samples, ~150-160 s per view on the Surface Pro 8), `gaming` (Cycles GPU 1080p).

## Layout

```text
config/variants/class_c.json         Coach parameters, truck spec (cab_chassis, reference, wheelbase_cc 5.3, duals)
config/variants/_ref_cab_chassis.json Bare cab-chassis reference render (skipped by --all)
config/render.json                   HDRI, road/ground, render profiles, cameras (same look as the camper repo)
config/paint.json                    Shared silver body paint (copied from the camper repo's config/v1.json)
scripts/render_variants.py           Render runner (truck + coach + environment, one view or several)
scripts/variants/class_c.py          Coach builder (lower body, cabover, windows, door, awning, ladder, bikes)
scripts/lib/proxy_truck.py           Procedural pickup / cab-chassis and the reference-model cut (cab_chassis)
scripts/lib/{meshkit,materials,environment,contact_sheet,common}.py  Shared libraries (duplicated from the camper repo)
```

The shared libraries are deliberate copies of the camper repo's; they may drift. Coordinate changes by hand when one repo's render look changes.

### Cab-chassis frame

Origin = top of the frame rails, centred, 7 cm behind the cab back (`cab_back_y` = 0.07); +Y forward, +Z up, +X right, metres. The frame runs to `frame_end_y`, the road is at `ground_z` (about -0.80). The coach sits on the rails (z >= 0) from y = 0 rearward and extends forward over the cab (cab roof at `roof_z`, about 1.14 above the frame). Truck keys: `type: cab_chassis`, `source: reference|procedural`, `wheelbase_cc`, `frame_length_behind_cab`, `frame_top_z` (0.80), `frame_hw` (0.56), `dual_rear_wheels`, `cab` (procedural only; the reference model is always a crew cab).

`class_c` puts the entry door and awning on the passenger/curb side (`camper.door_side: 1`) and mirrors its `front34` camera to the right-front so the hero view shows the door side. On the reference cab-chassis the cabover underside is 0.115 m above the cab roof and the coach front wall 2 cm behind the cab back.

## Asset policy

Create original geometry and textures. Do not commit, upload, or redistribute proprietary SCS assets, extracted vehicle models, interiors, textures, sounds, or third-party Road Trip/F-150 assets without explicit redistribution permission. The reference truck is a render stand-in only. If supported integration requires shipping protected assets (including a cut-down SCS cab), stop that approach and record the limitation.

## Disclaimer

Unofficial fan-made mod. Not affiliated with, sponsored by, or endorsed by Ford Motor Company or SCS Software. Ford, F-150 and Super Duty are trademarks of Ford Motor Company; American Truck Simulator is a trademark of SCS Software. Names are used only to identify the vehicle this mod fits. No Ford or SCS logos, models, or game assets are included.

## Credits

Preview renders use a third-party truck model as a stand-in base vehicle, cut behind the cab into a reference cab-chassis. It is used only for those preview renders: it is downloaded by hand into the tools folder (gitignored), never committed, never exported, and not included in the mod or any release package.

"2023 Ford F150 Lihtning Platinum" (https://skfb.ly/pFtDT) by tonielpro520 is licensed under Creative Commons Attribution (http://creativecommons.org/licenses/by/4.0/). Modified: badges removed, repainted, camper added.
