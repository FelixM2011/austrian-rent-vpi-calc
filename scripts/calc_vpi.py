#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CPI/VPI rent adjustment for indexed-rent leases (generic; data source: Statistics Austria OGD).

Strictly computes ONLY from available data. If a value cannot be found, the script
prints an error message and exits with code 2 — nothing is estimated, interpolated or invented.

Sources:
  1) Object data : <skill>/properties/<name>/data.json
     (template: TEMPLATE.json in this skill directory)
  2) Index dataset: open data from Statistics Austria, file vpi_ogg_c-vpizr-0.csv under
     <skill>/vpi_cache/source/. Key columns: C-VPIZR- (row key), C-VPI5- (series id, main
     series 'VPI-0'), F-VPIMZVM (absolute monthly CPI index) and F-VPIMZVJM
     (annual index, base year 2015=100).

Clause types:
  * clause_type = 'index'     -> pure index clause, 1:1, cumulative.
  * clause_type = 'threshold' -> threshold-type clause as found in many leases: only once the
    contractually agreed value (threshold_pct) is reached does the rent jump to the current
    index level immediately — not cumulatively on top of previous amounts.

Base month defaults to the month before lease start; if the contract states an explicit base
date, 'base_month' must be set in data.json.

Status & disclaimer (every output carries this):
  Status: November 2026. No warranty or guarantee of accuracy, completeness, legality, tax
  treatment or fitness for any purpose. Every result must be reviewed against the complete
  lease contract; statutory caps/limits are NOT checked by this script. The author is not a
  lawyer and not a tax advisor — no legal or financial advice is given.

Usage:
  python3 scripts/calc_vpi.py <properties>/<name>/data.json [--month YYYY-MM] \
      [--csv PATH_OVERRIDE] [--json]
Without the profile argument: show status of the local index dataset only.
"""
from __future__ import annotations

import argparse, csv, json, re, sys
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

SKILL_DIR   = Path(__file__).resolve().parent.parent
DEFAULT_CSV = SKILL_DIR / "vpi_cache" / "source" / "vpi_ogg_c-vpizr-0.csv"
SERIE       = "VPI-0"                       # main series (Statistics Austria, 2015=100)
EXIT_ERR    = 2

# ------------------------------------------------------------------ notices

STATUS_NOTE_SHORT = (
    "[NOTICE - review only] Status: November 2026. No guarantee of accuracy or correctness; "
    "every result must be reviewed against the complete lease contract. Statutory caps/limits "
    "(where applicable) are NOT checked by this script."
)

DISCLAIMER_BLOCK = (
    "*** STATUS & DISCLAIMER - NOVEMBER 2026, REVIEW ONLY ***\n"
    "Status of this skill and its results: November 2026.\n"
    "This tool provides NO WARRANTY OR GUARANTEE OF ACCURACY, CORRECTNESS, COMPLETENESS,\n"
    "LEGALITY, TAX TREATMENT OR FITNESS FOR ANY PURPOSE. Every result printed by this\n"
    "skill is for REVIEW ONLY and must be checked against your complete lease contract\n"
    "(and current law) before it is used in any way.\n"
    "Statutory caps/limits (where applicable, e.g. national rent-protection or indexation rules)\n"
    "were NOT verified by this script - no legal or financial advice is given here;\n"
    "in case of doubt seek professional legal/tax advice.\n"
    "Author of this skill: Felix Morocutti (https://github.com/FelixM2011).\n"
    "The author is NEITHER a lawyer NOR a tax advisor and assumes no liability for\n"
    "results produced with or relayed from this tool."
)


def die(msg: str) -> None:
    print("[ERROR] " + msg, file=sys.stderr)
    sys.exit(EXIT_ERR)


# ------------------------------------------------------------------ parsing

def to_number(value):
    """int/float/string (European comma decimal supported too) => Decimal or None."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text or text.lower() in ("?", "-", "n/a", "null"):
        return None
    if "," in text:                      # assume European style '1.234,56' -> 1234.56
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def to_yyyymm(value):
    """'YYYY-MM' => validated 'YYYY-MM', otherwise None."""
    t = str(value or "").strip()
    if len(t) != 7 or t[4] != "-" or not (t[:4].isdigit() and t[5:].isdigit()):
        return None
    m, y = int(t[5:]), int(t[:4])
    return f"{y:04d}-{m:02d}" if 1 <= m <= 12 else None


def previous_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:]) - 1
    if m == 0:
        y -= 1; m = 12
    return f"{y:04d}-{m:02d}"


def _thousands_group(digits: str) -> str:
    """'1234567' => '1,234,567' (grouping from the right)."""
    if len(digits) <= 3:
        return digits
    first = len(digits) % 3 or 3          # first chunk has 1-3 digits, rest in blocks of three
    return ",".join([digits[:first]] + [digits[i:i+3] for i in range(first, len(digits), 3)])


def fmt_money(d: Decimal) -> str:
    """Decimal => monetary amount '1,234.56' (two decimals, half-up)."""
    v = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    g, k = f"{abs(v):f}".split(".")        # fixed 'zzz.zz' shape
    return ("-" if v < 0 else "") + (_thousands_group(g) + "." + k)


def fmt_index(d: Decimal) -> str:
    """Decimal => index with one decimal, e.g. '124.5'."""
    v = d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    g, k = f"{abs(v):f}".split(".")
    return ("-" if v < 0 else "") + (_thousands_group(g) + "." + k)


def fmt_pct(d: Decimal) -> str:
    """Decimal => percentage with one decimal, e.g. '3.0 %' (sign preserved)."""
    v = d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    g, k = f"{abs(v):f}".split(".")
    prefix = "-" if v < 0 else ""
    return f"{prefix}{_thousands_group(g)}.{k} %"


# ------------------------------------------------------------------ loading

def load_profile(path: Path) -> dict:
    """Load data.json; required fields are checked strictly (no defaults invented)."""
    if not path.is_file():
        die(f"Data file not found: {path}\n"
            f"Please create it under <skill>/properties/<name>/data.json first "
            f"(reference: TEMPLATE.json in the skill directory).")
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"Data file is not valid JSON ({e}).")
    if not isinstance(d, dict):
        die("data.json must be a JSON object.")
    for f in ("name", "location", "street", "house_number"):
        if str(d.get(f) or "").strip() == "":
            die(f"Required profile field is missing: '{f}'")
    objs = d.get("objects")
    if not isinstance(objs, list) or not objs:
        die("Field 'objects' is missing or empty (at least one leased unit is required).")
    return d


def load_index(csv_path: Path):
    """Monthly and annual indices of the main series from the OGD/OGC CSV file."""
    if not csv_path.is_file():
        die(f"Index dataset not found at:\n  {csv_path}\n"
            "Please download/load the current dataset (scripts/vpi_fetch.py). NOTHING is estimated.")
    try:
        rows = list(csv.reader(csv_path.open(encoding="utf-8-sig", newline=""), delimiter=";"))
    except Exception as e:
        die(f"Index dataset could not be read ({e}) - please reload it (scripts/vpi_fetch.py).")
    if not rows or len(rows) < 2:
        die("Index dataset is empty/corrupt - please refresh the file (scripts/vpi_fetch.py).")
    hdr = [re.sub(r"-\d+$", "", c.strip()) for c in rows[0]]   # e.g. 'C-VPIZR-0' -> 'C-VPIZR-'
    try:
        i_key = hdr.index("C-VPIZR")
        i_ser = hdr.index("C-VPI5")
        i_mon = hdr.index("F-VPIMZVM")   # absolute monthly CPI index (2015=100)
    except ValueError:
        die(f"Unexpected header in the index dataset: {hdr}\n"
            "Please use the current OGD variant vpi_ogg_c-vpizr-0.csv.")

    months: dict[str, Decimal] = {}
    years:  dict[str, Decimal] = {}
    for r in rows[1:]:
        if len(r) <= max(i_key, i_ser, i_mon):
            continue
        key, serie = r[i_key].strip(), r[i_ser].strip()
        if serie != SERIE or not key.startswith("VPIZR-"):
            continue
        per  = key[len("VPIZR-"):]
        m_v  = to_number(r[i_mon])
        j_raw = r[hdr.index("F-VPIMZVJM")] if "F-VPIMZVJM" in hdr else None
        j_v   = to_number(j_raw)
        if len(per) == 6:                       # monthly row YYYYMM
            mm = int(per[4:])
            if m_v is None or not 1 <= mm <= 12:
                die(f"Row '{key}' contains no readable monthly index value - file corrupt? Please refresh.")
            months[f"{per[:4]}-{mm:02d}"] = m_v
        elif len(per) == 4 and per.isdigit():   # annual row YYYY
            if j_v is not None:
                years[per] = j_v              # relative annual index (2015=100)
    if not months:
        die("No monthly indices of the main series in the dataset - please refresh the file (scripts/vpi_fetch.py).")
    return months, years


def latest_index_up_to(months: dict, target_ym: str):
    """Last AVAILABLE monthly index <= target (no interpolation/estimation!)."""
    ok = [m for m in months if m <= target_ym]
    if not ok:
        die(f"No monthly index exists for '{target_ym}' or earlier "
            f"(dataset covers {min(months)} ... {max(months)}). Please refresh the OGD CSV.")
    m = sorted(ok)[-1]
    return m, months[m]


# ------------------------------------------------------------ calculation

def compute_object(o: dict, months: dict, target_ym: str) -> dict:
    """Check all required fields strictly; missing data => error entry in the result."""
    errors = []
    typ = str(o.get("type") or "").strip()
    if not typ:
        errors.append("'type' is missing (e.g. Apartment, Garage, Commercial unit ...)")

    rent = to_number(o.get("rent_eur"))
    if rent is None or rent <= 0:
        errors.append(f"'rent_eur' is missing, null or not positive - the exact monthly rent "
                      f"from the contract is required (found: {o.get('rent_eur')!r})")

    start = to_yyyymm(o.get("start_date"))
    if start is None:
        errors.append(f"'start_date' in YYYY-MM format is missing or malformed (found: {o.get('start_date')!r})")

    clause_raw  = str(o.get("clause_type", "index")).strip().lower()
    clause_kind = clause_raw if clause_raw in ("index", "threshold") else None
    if clause_kind is None:
        errors.append(f"unknown 'clause_type' {clause_raw!r} - only 'index' or 'threshold' are allowed")

    thresh = to_number(o.get("threshold_pct"))
    if clause_kind == "threshold" and thresh is None:
        errors.append("clause_type='threshold': the exact %-value from the contract is missing "
                      "(field 'threshold_pct')")

    if errors:
        dn = str(o.get("door_no") or "").strip()
        lbl  = f"{typ or '(missing)'}, {dn}" if dn else (typ or "(missing)")
        return {"type": typ or "(missing)", "_label": lbl, "errors": errors}

    dn    = str(o.get("door_no") or "").strip()
    label = f"{typ}, {dn}" if dn else typ

    bm_raw       = str(o.get("base_month", "")).strip()
    if bm_raw:                                    # explicitly set -> strict check, otherwise default
        bw = to_yyyymm(bm_raw)
        if bw is None:
            return {"type": typ, "_label": label,
                    "errors": [f"'base_month' has no YYYY-MM format (found: '{bm_raw}') - please set the exact contract value"]}
        base_ym       = bw
        base_origin   = "as stated in the contract"
    else:                                        # default: month before lease start
        base_ym       = previous_month(start)
        base_origin   = f"default (month before lease start {start})"

    if base_ym not in months:
        return {"type": typ, "errors": [
            f"monthly index for {base_ym} is not present in the local dataset "
            f"(datasets starts from {min(months)}). NOTHING is estimated - please refresh "
            f"the OGD file or verify/set 'base_month' in data.json."]}

    t_m, v_t = latest_index_up_to(months, target_ym)
    v_b      = months[base_ym]
    pct      = (v_t / v_b - 1) * 100            # change in % versus base month
    new_d    = rent * (v_t / v_b)

    r = {
        "type": typ,
        "_label": label,
        "old_rent_eur": fmt_money(rent),
        "base_month": base_ym,
        "base_origin": base_origin,
        "index_base": fmt_index(v_b),
        "index_used": {"month": t_m, "value": fmt_index(v_t)},
        "index_change_pct": f"{pct.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}",
    }
    r["index_note"] = (f"target month {target_ym} is not in the dataset yet - the last available "
                       f"monthly index value for {t_m} was used") if t_m != target_ym else None

    if clause_kind == "threshold":
        reached = pct >= thresh
        new_final = new_d if reached else rent
        r["clause"]  = (f"threshold clause, contractually agreed {fmt_pct(Decimal(thresh))} - increase "
                        f"{'is reached' if reached else 'is NOT reached yet'}")
    else:
        new_final   = new_d
        r["clause"]     = "pure index clause 1:1 (running monthly, cumulative)"
    r["new_rent_eur"] = fmt_money(new_final)
    # raw internal text values (no back-parsing from formatted strings; JSON-serialisable too):
    r["_delta_eur_raw"]  = str(new_final - rent)     # signed EUR difference as decimal string

    if pct < 0:
        r["negative_note"] = ("index below base - a reduction is only possible if the contract "
                              "allows one; otherwise the previous rent stays in place.")
    return r


# ------------------------------------------------------------- output + main

def print_profile_header(profil: dict) -> None:
    print("=" * 64)
    print("CPI/VPI RENT ADJUSTMENT (INDEXED-RENT CLAUSE)")
    print("=" * 64)
    print(STATUS_NOTE_SHORT)
    print(f"Property : {profil.get('name')}")
    addr = f"{profil.get('location')}, {profil.get('street')} {profil.get('house_number')}"
    dn   = str(profil.get("door_no", "")).strip()
    if dn:
        addr += " (door/top no.: " + dn + ")"
    print(f"Address  : {addr}")
    kt = profil.get("clause_text")
    if str(kt or "").strip():
        print('Contractual clause text\n(verbatim from the lease): "'
              + str(kt).strip().replace("\n", " ")
              + '"')


def main() -> int:
    ap = argparse.ArgumentParser(description="CPI/VPI rent adjustment (indexed-rent clause)")
    ap.add_argument("profil", nargs="?", help="Path to properties/<name>/data.json")
    ap.add_argument("--month", "--target", dest="target_month", default=None, metavar="YYYY-MM",
                    help="Target month (default: current calendar month)")
    ap.add_argument("--csv", default=str(DEFAULT_CSV),
                    help="Path to the index CSV file (default: local OGD snapshot)")
    ap.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    a = ap.parse_args()

    months, years = load_index(Path(a.csv))
    status = {"source": str(Path(a.csv).resolve()), "series": SERIE,
              "base_year": "2015=100 (per OGD metadata)",
              "months_min": min(months), "months_max": max(months)}

    if not a.profil:                       # pure status mode
        print("Status of the local index dataset")
        for k, v in status.items():
            print(f"  {k}: {v}")
        print()
        print(STATUS_NOTE_SHORT)
        return 0

    profil = load_profile(Path(a.profil))
    target = to_yyyymm(a.target_month) if a.target_month else date.today().strftime("%Y-%m")
    if a.target_month and target is None:
        die(f"--month '{a.target_month}' is not a valid YYYY-MM month.")

    error_list, results = [], []
    for o in profil["objects"]:
        r = compute_object(o, months, target)
        if "errors" in r:
            error_list.append(r["type"])      # display after the data header (below)
        results.append(r)

    ok = [r for r in results if "errors" not in r]

    if a.json:
        payload = {"profil": profil, "index_status": status, "target_month": target,
                   "status_note": STATUS_NOTE_SHORT,
                   "disclaimer": DISCLAIMER_BLOCK,
                   "objects": results}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_profile_header(profil)
        print(f"Index data : monthly values {status['months_min']} ... {status['months_max']}, "
              f"series {SERIE} [OGD snapshot, base year 2015=100]")
        if years.get(target[:4]) is not None:
            print(f"Annual index {target[:4]} (closed): {fmt_index(years[target[:4]])}")
        zz = "current calendar month" if a.target_month is None else "given via --month"
        print(f"Computed  : for target month {target} ({zz})")

        if error_list:                                      # error messages after the data header,
            print()                                          # printed before the per-object blocks
            for r in results:
                if "errors" not in r:
                    continue
                print(f"[ERROR] object ({r['type']}):")
                for f in r["errors"]:
                    print("   - " + f)

        for r in results:
            if "errors" in r:
                continue                                     # shown above in the error section
            diff = Decimal(r["_delta_eur_raw"])             # signed difference as decimal string, e.g. "315.04"
            print("-" * 64)
            print(f"Object ({r['type']}) - clause: {r['clause']}")
            print(f"  Basis        : old rent {r['old_rent_eur']} EUR/month; "
                  f"base month {r['base_month']} = monthly index {r['index_base']} "
                  f"[{r['base_origin']}]")
            used    = r["index_used"]
            extra   = "" if used["month"] == target else f"   [NOTE: {r.get('index_note')}] "
            print(f"  Index value  : monthly index for {used['month']} -> index {used['value']}{extra}")
            pct_d = Decimal(r["index_change_pct"])
            sign  = "-" if pct_d < 0 else "+"
            g, k  = str(abs(pct_d).quantize(Decimal('0.1'))).split(".")
            print(f"  Change       : {sign}{_thousands_group(g)}.{k} % versus base month")
            note_r = r.get("negative_note")
            if note_r:
                print("  NOTE         : " + note_r)
            sign2  = "-" if diff < 0 else "+"
            dg, dk = str(abs(diff).quantize(Decimal('0.01'))).split(".")
            print(f"  RESULT       : old rent {r['old_rent_eur']} EUR/month "
                  f"-> new rent {r['new_rent_eur']} EUR/month "
                  f"(difference: {sign2}{dg}.{dk} EUR)")

        if not ok:
            print()
            print(STATUS_NOTE_SHORT)
            die("No object could be fully computed - please provide the missing contract data.")

    if not a.json:                        # JSON stays machine-readable (notice is carried as a field there)
        print()
        print(DISCLAIMER_BLOCK)
    return EXIT_ERR if error_list else 0


if __name__ == "__main__":
    sys.exit(main())
