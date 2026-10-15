# Roadmap

All items start unverified. This records intent, not completed implementation. Split from the camper repo's former "Phase 3 — F-150-cab-based Class C RV" on October 15, 2026. Shared feasibility work (ATS/Road Trip versions, def paths, paint mechanism, toolchain pins) lives in the camper repo's `docs/compatibility.md`; do not duplicate it here, link to it.

## Phase 0 — Preview (done, render-only)

- [x] Original coach geometry: lower body, cabover berth with wraparound glass, windows cut as pockets with tinted panes, curb-side entry door, awning, roof units, ladder, rear bumper and bike rack. No logos or lettering.
- [x] Reference cab-chassis for renders: CC BY crew-cab model cut 12 mm behind the cab, openings capped, procedural frame/crossmembers/axle/springs, dual rear wheels copied from the model's own wheel, `wheelbase_cc` 5.3.
- [x] Standalone render pipeline (copied libraries, tools path resolved to the sibling camper repo).
- Known issue: Eevee glass and interior brightness/sorting artifacts; Cycles is the reference look.

## Target vehicle (Rob, 2026-10-15)

- **Chassis:** a 2-door regular-cab Super Duty-style chassis cab (F-350/F-450 class) with dual rear wheels, badge-free. Not the half-ton F-150 crew cab the current preview uses.
- **Renders:** swap the reference cab-chassis for a CC-BY or CC0 Sketchfab model of such a chassis cab if one turns up (credit it in the README, keep it in the tools folder, never commit or package it; debadge it like the current reference).
- **Game:** build ORIGINAL geometry from Ford's public Body Builders Layout Book dimensions (wheelbase, cab-to-axle, frame height and width, cab envelope). A lookalike, not a replica: alter the grille and lights, no Ford badges, names or logos, no SCS or Ford model data.
- **Open gate (gaming PC):** can a mod add a new Road Trip *car* (`def/vehicle/car/...`, dealer `vehicle : .car` entries), or would this have to be a mod *truck* def (`def/vehicle/truck/...`), losing Road Trip car features (car dealer, car interior/camera behaviour, Road Trip-specific systems)? Verify by extracting the Road Trip defs and checking whether the car dealer, vehicle lists and car physics accept a third-party car unit, then load a tiny original test car; compare with an existing community car or truck mod. Record the answer here and in the camper repo's docs/compatibility.md.

## Phase 1 — Cab decision (blocking)

Road Trip ships only the 4-door crew cab (cabin `pckup4d_55.ford.f150_23.cabin`, chassis `4d55_awd.ford.f150_23.chassis`; OBSERVED-IN-MODS, see the camper repo). A Class C is normally a 2-door regular cab, but we cannot ship a cut-down or modified SCS model.

- [ ] Option A: keep the installed crew cab and design the coach around it (longer vehicle, reuses the game's cab, interior and controls if a chassis swap can reference them).
- [ ] Option B (Rob's target, see above): build an original 2-door regular-cab Super Duty-style chassis cab from the Body Builders Layout Book dimensions (all-new exterior, likely a new interior, far larger scope; no SCS geometry). Depends on the car-vs-truck gate.
- [ ] Record the decision and its consequences here before modeling further. Re-render the preview on the chosen cab.

## Phase 2 — Chassis feasibility (gaming PC)

- [ ] Find out how Road Trip cars define chassis (`def/vehicle/car/ford.f150_23/chassis/`): whether a mod can add a new chassis with a different wheelbase, dual rear wheels and its own model while referencing the installed cab, engine, transmission and interior without redistributing them.
- [ ] Check cameras, collision (.pmc), suspension and physics data for cars; record which values a new chassis must supply.
- [ ] Tiny proof: an original box "chassis" on a stretched wheelbase loads and drives on a test profile.

## Phase 3 — Coach for the game

- [ ] Rebuild the coach for export: UVs, materials, LODs, collision, SCS locators, using the camper repo's export/convert/package pipeline as the template.
- [ ] Paint: decide whether the cab follows body colour and the coach is fixed gelcoat; verify the paint mechanism in game.
- [ ] Validate visuals and driving on a separate test profile before release; compare handling with the stock F-150.

Deliverables: cab decision record, chassis feasibility report, original coach source, build scripts, release candidate and full game test evidence.
