# Roadmap

All items start unverified. This records intent, not completed implementation. Split from the bed-accessories repo's former "Phase 3 — Class C RV" on October 15, 2026. Shared feasibility work (ATS/Road Trip versions, def paths, paint mechanism, toolchain pins) lives in the bed-accessories repo's `docs/compatibility.md`; do not duplicate it here, link to it. Open Class C gates live in [docs/compatibility.md](docs/compatibility.md).

## Phase 0 — Preview (done, render-only)

- [x] Original coach geometry: lower body, cabover berth with wraparound glass, windows cut as pockets with tinted panes, curb-side entry door, awning, roof units, ladder, rear bumper and bike rack. No logos or lettering.
- [x] Reference HD chassis cab for renders (2026-10-15): the preview now uses a 1999–2007-generation heavy-duty regular-cab reference (CC BY pickup, scaled to a 2.03 m body width, cut 12 mm behind the cab, openings capped, fully debadged, plates removed, repainted white to match the coach) with front and dual rear wheel assemblies from a CC BY-SA derived chassis-cab model, a procedural frame, rear axle, leaf springs, fuel tank and exhaust. Wheelbase 4.19 m (165 in, the long one-ton DRW chassis-cab wheelbase), coach ~7.3 m bumper to rear wall, cabover 0.12 m above the cab roof. Previews are BY-SA adaptations (README Credits). Fallback: the procedural chassis.
- [x] Standalone render pipeline (copied libraries).
- [ ] Coach style (Rob, 2026-10-16: the rounded coach is "big and bulbous", wants the hard-edged slide-in look scaled to the chassis): preview options A `class_c_slide_in_exact` and B `class_c_slide_in_styled` (`camper.style`; the rounded coach stays selectable). Pick one, then refine.
- Known issues: Eevee glass and interior brightness/sorting artifacts (Cycles is the reference look); a faint remnant of the grille-badge mount stem is still visible on the centre grille bar in close-ups (no lettering).

## Target vehicle (Rob, 2026-10-15)

- **Chassis:** a 2-door regular-cab heavy-duty (one-ton to 1.5-ton class) chassis cab with dual rear wheels, badge-free.
- **Renders:** done with the reference HD chassis cab above (credited in the README, kept in the tools folder, never committed or packaged).
- **Game:** still ORIGINAL geometry, built from Ford's public Body Builders Layout Book dimensions (wheelbase, cab-to-axle, frame height and width, cab envelope). The render reference is not used for the game model. A lookalike, not a replica: alter the grille and lights, no Ford badges, names or logos, no SCS or third-party model data.
- **Open gate (gaming PC):** can a mod add a new Road Trip *car* (`def/vehicle/car/...`, dealer `vehicle : .car` entries), or would this have to be a mod *truck* def (`def/vehicle/truck/...`), losing Road Trip car features (car dealer, car interior/camera behaviour, Road Trip-specific systems)? Verify by extracting the Road Trip defs and checking whether the car dealer, vehicle lists and car physics accept a third-party car unit, then load a tiny original test car; compare with an existing community car or truck mod. Record the answer here and in docs/compatibility.md.

## Phase 1 — Cab decision (blocking)

Road Trip ships only a 4-door crew-cab pickup (unit names: see the bed-accessories repo's compatibility notes). A Class C is normally a 2-door regular cab, but we cannot ship a cut-down or modified SCS model.

- [ ] Option A: keep the installed crew cab and design the coach around it (longer vehicle, reuses the game's cab, interior and controls if a chassis swap can reference them).
- [ ] Option B (Rob's target, see above): build an original 2-door regular-cab heavy-duty chassis cab from the Body Builders Layout Book dimensions (all-new exterior, likely a new interior, far larger scope; no SCS geometry). Depends on the car-vs-truck gate.
- [ ] Record the decision and its consequences here before modeling further.

## Phase 2 — Chassis feasibility (gaming PC)

- [ ] Find out how Road Trip cars define chassis (the installed pickup's `chassis/` defs): whether a mod can add a new chassis with a different wheelbase, dual rear wheels and its own model while referencing the installed cab, engine, transmission and interior without redistributing them.
- [ ] Check cameras, collision (.pmc), suspension and physics data for cars; record which values a new chassis must supply.
- [ ] Tiny proof: an original box "chassis" on a stretched wheelbase loads and drives on a test profile.

## Phase 3 — Coach for the game

- [ ] Rebuild the coach for export: UVs, materials, LODs, collision, SCS locators, using the bed-accessories repo's export/convert/package pipeline as the template.
- [ ] Paint: decide whether the cab follows body colour and the coach is fixed gelcoat; verify the paint mechanism in game.
- [ ] Validate visuals and driving on a separate test profile before release; compare handling with the stock Road Trip pickup.

Deliverables: cab decision record, chassis feasibility report, original coach source, build scripts, release candidate and full game test evidence.
