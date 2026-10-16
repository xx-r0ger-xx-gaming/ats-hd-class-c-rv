# ATS Road Trip — Class C Motorhome on a Heavy-Duty Chassis Cab

A compact Class C motorhome (cabover berth, rear habitation body, dual rear wheels) built on a two-door, badge-free, heavy-duty (one-ton-style) regular-cab chassis cab. Target game: American Truck Simulator - Road Trip: Ford. Split on October 15, 2026 out of the bed-accessories repo ([ats-f150-bed-accessories](https://github.com/xx-r0ger-xx-gaming/ats-f150-bed-accessories)), because a Class C needs its own chassis rather than a truck-bed accessory slot.

Start with [CLAUDE.md](CLAUDE.md), then [the roadmap](docs/roadmap.md). Open gates: [docs/compatibility.md](docs/compatibility.md).

## Status

**Preview renders only.** Nothing here is exported, converted, packaged or tested in game, and a render is not proof that a mod works. Current state:

- The coach is original, render-only geometry (`scripts/variants/class_c.py`), about 7.3 m from front bumper to rear wall.
- The base vehicle in the renders is a **reference HD chassis cab** (`truck.source: hd_reference`): a downloaded 1999–2007-generation heavy-duty regular-cab pickup (see Credits) scaled to real size, cut 12 mm behind the cab, cut openings capped, fully debadged (grille oval and its mount, fender and door badges, plates and plate bracket removed; the bed with its tailgate badges and decals is cut away), repainted to match the coach, plus dual-rear-wheel and front wheel assemblies from a derived chassis-cab model and a procedural frame, crossmembers, rear axle, leaf springs, fuel tank and exhaust. It is a render construct, **not a measured chassis cab**.
- **Wheelbase 4.19 m (165 in)**, the long one-ton DRW chassis-cab wheelbase in the public body-builder layout data; cab back to rear axle about 2.2 m, rear overhang about 2.1 m behind the axle (about 51 % of the wheelbase). The cabover underside is 0.12 m above the cab roof and the coach front wall sits 2 cm behind the cab back.
- **Tyres:** the extracted wheel assemblies (245/75R17 class, 0.796 m on 17 in wheels, rear pair touching) are reshaped at build time (`HD_CHASSIS_DEFAULTS`) to a 225/70R19.5-class DRW setup: 0.82 m tyres on 19.5 in wheels front and rear, rear duals 0.275 m centre to centre (~3.5 cm sidewall gap), pair centre 0.957 m off the centreline so the outer sidewall sits ~3 cm inside the 2.50 m coach side (overall dual width ~2.43 m, was 2.24 m). The coach rear arch follows the rear tyre with ~9 cm clearance (radius 0.50 m, was 0.58).
- **Coach styles (2026-10-16, exploratory):** `camper.style` selects the coach. `rounded` (`class_c`) is the original bulbous coach. Two hard-edged **slide-in style** options (`scripts/variants/slide_in_style.py`) are up for review: `class_c_slide_in_exact` (option A: the slide-in camper look scaled onto the chassis, wing walls above the duals on a narrow basement, rear entry door, corner jacks, roof 2.41 m above the frame) and `class_c_slide_in_styled` (option B: same profile, edges, windows and graphics with Class C proportions: full-width lower body to the skirt with squared rear arches, cabover nose out to 1.98 m, curb-side entry door and awning). Both keep the chassis, wheels and wheelbase.
- **In game the plan is unchanged:** original geometry built from public body-builder dimensions, not this reference model (see the roadmap).
- **Eevee glass artifacts:** the `surface` (Eevee) profile shows the coach windows and interiors much brighter than Cycles and has glass sorting artifacts. Judge glass and windows in Cycles (`surface-photo` or `gaming`).

## Tools

`tools/` (gitignored, about 1.5 GB) holds this repo's own toolchain and reference models; nothing is shared with another checkout. Populate it with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/fetch_tools.ps1   # Blender 3.6.23 portable, SCS Blender Tools, HDRI (sha256-checked)
```

then add the reference models below. Paths starting with `tools/` resolve to `./tools`, unless the `ATS_TOOLS_DIR` environment variable or `"tools_dir"` in `config/tools.local.json` (gitignored; copy `config/tools.example.json`) points elsewhere.

### Reference models for preview renders

Download both models from Sketchfab as glTF binary (.glb) into `tools/reference-hd-chassis/` (gitignored) and rename them:

- the regular-cab pickup (first credit below) → `hd_regular_cab_pickup.glb`
- the chassis-cab box truck (second credit) → `hd_drw_box_truck.glb`

Then extract the wheel assemblies once (imports the 2.35M-face box truck in its own Blender process and writes `tools/reference-hd-chassis/hd_drw_wheels.blend`, about 100 MB):

```bash
$B --background --factory-startup --python-exit-code 1 --python scripts/extract_hd_wheels.py
```

Both .glb files are checked as valid glTF 2.0 before import. The object names the debadge step removes are those of these exact downloads (`HD_CHASSIS_DEFAULTS` in `scripts/lib/proxy_truck.py`); a different download fails loudly.

## Rendering

```bash
B=tools/blender-3.6.23-windows-x64/blender.exe
# Cycles CPU, one view per Blender process (the Surface Pro has stopped on low memory with several)
for v in rear34 side front34; do
  $B --background --factory-startup --python-exit-code 1 --python scripts/render_variants.py -- \
     --variant class_c --profile surface-photo --views $v --no-sheet
done
# (drop --no-sheet on the last run to rebuild renders/variants/contact_sheet.png)
# bare base vehicle
$B ... -- --variant _ref_cab_chassis
```

Outputs go to `renders/variants/<name>_<view>.png` (gitignored), run evidence to `logs/render_variants-<timestamp>.json` (settings, camera, sun, seconds, output sha256). `--set key.path=value` overrides config keys (e.g. `--set truck.source=procedural` renders on the procedural regular-cab chassis, the fallback when the reference models are not present), `--suffix` renames the outputs. Profiles and views are in `config/render.json`: `surface` (Eevee 1280x720, 32 samples), `surface-photo` (Cycles CPU, 192 adaptive samples, ~3-4 min per view on the Surface Pro 8 with the reference chassis), `gaming` (Cycles GPU 1080p).

## Layout

```text
config/variants/class_c.json          Coach parameters, truck spec (cab_chassis, hd_reference, wheelbase_cc 4.19, duals)
config/variants/class_c_slide_in_{exact,styled}.json  Slide-in style coach options A / B (camper.style)
config/variants/_ref_cab_chassis.json Bare chassis-cab reference render (skipped by --all)
config/render.json                    HDRI, road/ground, render profiles, cameras
config/paint.json                     Cab paint (solid white matched to the coach)
scripts/render_variants.py            Render runner (truck + coach + environment, one view or several)
scripts/fetch_tools.ps1               Toolchain download into ./tools (Blender, SCS add-on, HDRI; sha256-checked)
scripts/extract_hd_wheels.py          One-off: DRW wheel assemblies from the box-truck reference to a small .blend
scripts/variants/class_c.py           Coach builder (lower body, cabover, windows, door, awning, ladder, bikes)
scripts/variants/slide_in_style.py    Slide-in style coaches (hard-edged profile, framed windows, swoosh graphics), called from class_c.py
scripts/lib/proxy_truck.py            Procedural pickup / cab-chassis and the HD reference chassis cab (hd_reference)
scripts/lib/{meshkit,materials,environment,contact_sheet,common}.py  Shared libraries (duplicated from the bed-accessories repo)
```

The shared libraries are deliberate copies; they may drift. Coordinate changes by hand when the render look changes.

### Cab-chassis frame

Origin = top of the frame rails, centred, 7 cm behind the cab back (`cab_back_y` = 0.07); +Y forward, +Z up, +X right, metres. The frame runs to `frame_end_y`, the road is at `ground_z` (-0.80). The coach sits on the rails (z >= 0) from y = 0 rearward and extends forward over the cab (cab roof at `roof_z`, about 1.14 above the frame). Truck keys: `type: cab_chassis`, `source: hd_reference|procedural`, `wheelbase_cc`, `frame_length_behind_cab`, `frame_top_z` (0.80), `frame_hw`, `dual_rear_wheels`, `cab` (procedural only). Coach keys that follow the chassis: `rear_y` (-4.20), `cabover_bottom_z` (1.26), `roof_z` (2.52).

`class_c` puts the entry door and awning on the passenger/curb side (`camper.door_side: 1`) and mirrors its `front34` camera to the right-front so the hero view shows the door side.

## Asset policy

Create original geometry and textures. Do not commit, upload, or redistribute proprietary SCS assets, extracted vehicle models, interiors, textures, sounds, or third-party vehicle models without explicit redistribution permission. The reference models are render-only. If supported integration requires shipping protected assets (including a cut-down SCS cab), stop that approach and record the limitation.

## Disclaimer

Unofficial fan-made mod. Not affiliated with, sponsored by, or endorsed by Ford Motor Company or SCS Software. Ford is a trademark of Ford Motor Company; American Truck Simulator is a trademark of SCS Software. Names are used only to identify the game content this mod targets. No manufacturer or SCS logos, models, or game assets are included.

## Credits

Preview renders use two third-party models for the base vehicle. They are used only for those preview renders: downloaded by hand into the tools folder (gitignored), never committed, never exported, and not included in the mod or any release package.

"F350 Superduty Highpoly" (https://sketchfab.com/3d-models/f350-superduty-highpoly-294a98fe36664803a0e495fbea7ac4d1) by Luquita is licensed under Creative Commons Attribution (http://creativecommons.org/licenses/by/4.0/). Modified: badges removed, repainted, cut to chassis cab, camper added. Not included in the mod.

"F350 Superduty Box Truck" (https://sketchfab.com/3d-models/f350-superduty-box-truck-18ba47d4608843629b296bd57e1921bc) by nero.77 is licensed under Creative Commons Attribution-ShareAlike (http://creativecommons.org/licenses/by-sa/4.0/). Modified: badges removed, repainted, cut to chassis cab, camper added. Not included in the mod. Its front and dual rear wheel assemblies (textures dropped, render materials applied) are used directly, so the preview renders are adaptations of it and are shared under CC BY-SA 4.0.
