# Class C compatibility gates

Shared Road Trip feasibility facts (def paths, unit names, paint mechanism, toolchain pins) live in the bed-accessories repo's [docs/compatibility.md](https://github.com/xx-r0ger-xx-gaming/ats-f150-bed-accessories/blob/main/docs/compatibility.md). This file holds only the Class C gates. Do not duplicate the shared facts here; link to them.

## Open gates

| # | Unknown | Resolve on gaming PC by |
| --- | --- | --- |
| 1 | Class C: can a mod add a new Road Trip *car* (`def/vehicle/car/`, car dealer entry), or must a regular-cab chassis cab be a mod *truck* def (losing Road Trip car features)? | In the extracted Road Trip defs, check how the car dealer and vehicle lists reference car units and whether a third-party car unit loads; try a tiny original test car on a test profile |
