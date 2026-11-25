---
name: austrian-rent-vpi-calc
description: Calculate Consumer Price Index (CPI/VPI)-based rent adjustments for residential, garage/parking and commercial lease profiles in Austria. Calculations are in the style of Austrian indexed-rent clauses; verify all results yourself before acting on them.
version: 1.0.0
author: Felix Morocutti (https://github.com/FelixM2011)
license: MIT
platforms: [linux, macos]
metadata.hermes.category: productivity
metadata.hermes.tags: [rent, index-clause, cpi, vpi, apartment, lease, calculation]
---

# Skill: CPI/VPI Rent Adjustment (indexed-rent clauses, property profile)

Computes the CPI-indexed rent adjustment for apartments, garages/parking spaces, commercial units and halves of two-family houses in Austria. All figures are computed strictly from
**locally available** index data (open-data snapshot from Statistics Austria) using `Decimal` — nothing is estimated or invented.

## Author & Status — read first

- **Status: November 2026.** This skill reflects the state of knowledge and data sources as of November 2026; it may be out of date at any later point.
- **No guarantee on correctness:** Results are provided without any warranty or liability of any kind, express or implied — including but not limited to accuracy, completeness, fitness for a particular purpose, legality, tax treatment and legal validity (no legal/financial/tax advice).
- **Every single output must be reviewed** by the user against the complete lease contract and current law before it is used in any way.
- The **author (Felix Morocutti, https://github.com/FelixM2011) is neither a lawyer nor a tax advisor** and cannot assume liability for results produced with this skill.
- Every result printed by the scripts (normal or JSON mode context blocks) carries the same review reminder in the language of that output — the user must keep these notices verbatim when relaying results to third parties, as they are part of the disclaimers above.

## When to Use

- The user asks about rent / index increase for a property with an indexed-rent clause, e.g. "Calculate the rent increase for my house at …" (location/street/house number, optionally door/top no.).
- An existing profile under `properties/<name>/data.json` should be re-calculated with current data.
- A new profile needs to be created first (collect the missing lease facts from the user — NEVER guess them).

## IMPORTANT — never invent data; always state the calculation basis

1. **No value is invented:** If something is missing in the profile or the index dataset, the script prints an error message and exits with code 2 (per object) respectively aborts. Your answer must then say "Missing data" + exactly which fields are needed — collect them from the user instead of filling them in yourself.
2. **Always state the calculation basis:** previous rent, base month (+ origin: explicit contract value or default = month before lease start), index values used (base & current; with a note if the target month was not published yet and the last available index had to be taken).
3. **Not binding / for review only:** The output ends with the disclaimer block shipped in `calc_vpi.py` — results are for review purposes only, NOT binding or actionable legal advice; statutory caps/limits (where applicable) are NOT checked by the script; the user must verify against the full contract and seek professional legal/tax advice in any case of doubt.

## Calculation Logic

- **Formula:** `new_rent = old_rent × index(current month) / index(base month)` per leased unit.
- **Base month:** Default is the *month before lease start*. If the contract specifies an explicit index base date (e.g. "index reference 1 Aug 2017"), set `base_month` in `data.json` — it will then appear in the output as "as stated in the contract".
- **Clause types** (`clause_type`, read verbatim from the lease):
  - `index` → pure index clause 1:1 (running monthly, cumulative).
  - `threshold` → threshold-type clauses found in many leases (often "only after +5 %" — the exact value always comes from the contract!): raise the rent immediately to the current index level ONLY if `(current/base − 1)×100 ≥ threshold`, otherwise keep the previous rent.
- **Target month:** Default = current calendar month; selectable via `--month YYYY-MM`. If the target month is not in the dataset (monthly CPI values are published about two weeks after month end), the last available earlier index is used and this is made visible as `[NOTE …]` — no interpolation.

## Procedure

### 1. Find or create a profile
- User names location/street/… → search `properties/<name>/data.json` (`search_files target=files pattern=*<street>*/data.json`). If present, load it; otherwise:
- **Collect the lease data from the user** (only what is actually in the contract):
  - verbatim clause text + paragraph/clause reference, lease start date (YYYY-MM), current monthly rent per unit,
  - clause type (`index` or `threshold`) and for `threshold`: the exact % threshold value,
  - if the contract states an explicit index base date: its calendar month for `base_month`.
- Create the profile based on `TEMPLATE.json`; empty fields may stay empty — the script then reports them as errors and the user must supply them (do NOT guess data).

### 2. Check the index data status
```bash
python3 scripts/vpi_fetch.py            # validates local snapshot; --force: automatic re-download from the OGD catalog (.bak backup)
python3 scripts/calc_vpi.py             # status mode only: month range + source
```
Local snapshot: `vpi_cache/source/vpi_ogg_c-vpizr-0.csv` (monthly indices, main series `VPI-0`, base year 2015=100; columns `F-VPIMZVM` = monthly index, `F-VPIMZVJM` = annual index).

### 3. Run the calculation
```bash
python3 scripts/calc_vpi.py "properties/<name>/data.json" \
    [--month YYYY-MM] [--csv PATH_OVERRIDE] [--json]
```
- Normal mode: calculation basis + result per object (two-digit rounded currency) + disclaimer block.
- `--json`: machine-readable output including `index_status` and the per-object error list (error entries carry text in the current language; keep them verbatim when relaying results).

### 4. Answer to the user
Always include: basis blocks, a reference to the index period actually used (e.g. "Monthly CPI values 2016-01 … 2025-12"), a short note for every object that could not be computed (missing data), and the non-binding/disclaimer text — in the language of your reply.

## Profile Data Format (`properties/<name>/data.json`)
```jsonc
{
  "name": "<Display name>", "nation": "AT",
  "location": "", "street": "", "house_number": "",   // used for look-up/address display
  "door_no": "",                                       // optional, property-level door/top no.
  "clause_text": "<verbatim from the lease>",          // displayed in the output
  "objects": [
    { "type": "Apartment",
      "street": "",   // optional per unit (when different from property level)
      "door_no": "Top 2/4",
      "rent_eur": 900,              // exact monthly rent from the contract — never guess!
      "start_date": "2017-12",      // lease start YYYY-MM
      "base_month": "",             // empty = default (month before start); else explicit contract reference date YYYY-MM
      "clause_type": "threshold",   // 'index' | 'threshold'
      "threshold_pct": 3 }          // only for 'threshold'; value from the contract — never guess!
    // … further units (garage, commercial unit, two-family-house half) are analogous … ]
}
```

## Error & Abort Behaviour (Script)
| Situation | Behaviour |
|---|---|
| data.json missing / not valid JSON | `[ERROR]` + exit code 2 (message with path hint, language of the script/current locale run) |
| Required field empty/invalid (rent, start date YYYY-MM, clause_type, threshold value for `threshold`) | `[ERROR] object …` in the result block; calculation skipped — **no defaults** |
| Base-month monthly index not available | Error: no estimation allowed (refresh the OGD file or verify the contract value) |
| Target month not published yet | last earlier available index + `[NOTE …]` in output (no silent break-out) |
| `--json` | same required-fields/errors as normal mode; exit code 2 **as soon as at least one** object has errors (also for mixed success status) — fully computed runs only give 0 |

## Pitfalls

- **Door/top designations** (e.g. "Top 2/4", "TG A2") are always free-text fields — never parse or normalise them.
- **Threshold type and value:** never assume a default ("often 5 %"); if it is not in the contract, ask the user instead of guessing (`clause_type` may then become `index`, or the threshold stays null → scripts report the error).
- **Contract reference date ≠ lease start:** when the contract names another date, set `base_month`; the origin will be shown as "as stated in the contract".
- The index dataset is only as current as the official open-data publication (monthly values about two weeks after month end). For target months beyond the snapshot, and always: use/announce the latest available index — mark it clearly. This remains a **review-only input**, must stay visible in any result you present.
- With multiple units per property: compute each unit independently; no aggregate "total calculation" (unless the contract explicitly requires another method → then handle it manually out-of-band).
- No statutory checks are performed automatically — only clause math plus mandatory reminder text.
