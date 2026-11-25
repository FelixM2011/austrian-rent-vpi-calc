#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check/refresh the CPI/VPI dataset (Statistics Austria open data).

Status & disclaimer: Status November 2026, no guarantee of accuracy or correctness;
every result from this tool line must be reviewed. See SKILL.md for the full notice block.

Checks the local snapshot at <skill>/vpi_cache/source/vpi_ogg_c-vpizr-0.csv (header plus
monthly indices of the main series must be readable). If the local file is missing or
unusable, an automatic download from the statdata.at OGD catalog is attempted (the old
version is kept in .bak first). If both fail, manual re-download instructions are printed.

Usage:  python3 scripts/vpi_fetch.py [--force]
"""
from __future__ import annotations

import csv, json, re, shutil, sys, tempfile, urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SRC       = SKILL_DIR / "vpi_cache" / "source" / "vpi_ogg_c-vpizr-0.csv"
BACKUP    = SRC.with_name("vpi_ogg_c-vpizr-0.csv.bak")
CATALOG   = "https://statdata.at/api/statistik/catalog?name=vpi"

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def manual_block() -> str:
    return (
        "\nManual re-download path (automatic download not possible):\n"
        " 1) On a machine with open network access, open in a browser:\n"
        f"      {CATALOG}\n"
        "    or: statistikaustria.gv.at -> 'Open Data' data portal (StatData)\n"
        " 2) Search for the dataset 'Consumer Price Index (VPI)' and download the current\n"
        "    CSV variant with columns C-VPIZR- / F-VPIMZVM\n"
        "    (official name: vpi_ogg_c-vpizr-0.csv).\n"
        f" 3) Copy the file exactly to this location:\n"
        f"      {SRC}\n"
        " 4) Re-validate with:   python3 scripts/vpi_fetch.py\n")


def check_file(path: Path) -> bool:
    """Is the header plus a minimum number of monthly indices readable?"""
    try:
        rows = list(csv.reader(path.open(encoding="utf-8-sig", newline=""), delimiter=";"))
    except Exception:
        return False
    if len(rows) < 12:
        return False
    hdr = [re.sub(r"-\d+$", "", c.strip()) for c in rows[0]]
    if "C-VPIZR" not in hdr or "VPI5" not in hdr or "F-VPIMZVM" not in hdr:
        return False
    months = 0
    for r in rows[1:]:
        if len(r) >= 3 and r[1].strip() == "VPI-0" and re.fullmatch(r"VPIZR-\d{6}", r[0]):
            months += 1
    return months >= 12


def catalog_csv_url():
    """Query the OGD catalog and find the direct CSV link of the VPI variant."""
    req = urllib.request.Request(CATALOG, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as f:
        kat = json.loads(f.read().decode("utf-8"))
    for key in ("DataSets", "datasets"):
        ds_list = kat.get(key)
        if not isinstance(ds_list, list):
            continue
        for ds in ds_list:
            nm = str(ds.get("Name") or ds.get("name") or "").lower()
            if "vpi" not in nm:
                continue
            for f2 in (ds.get("Files") or []):
                link = (f2.get("url") or f2.get("Url") or "").strip()
                if link.lower().endswith(".csv"):
                    return link
    return None


def main(force: bool) -> int:
    if not force and check_file(SRC):
        print("[OK] Local index file is current and readable (header + monthly indices).")
        return 0

    print("[INFO] Local file unusable or --force requested: attempting automatic re-download ...")
    try:
        url = catalog_csv_url()
    except Exception as e:
        print(f"[DOWNLOAD-CATALOG] not reachable ({e}).", file=sys.stderr)
        print(manual_block(), file=sys.stderr)
        sys.exit(2)
    if not url:
        print("[DOWNLOAD-CATALOG] no matching CSV found in the catalog (format mismatch?).", file=sys.stderr)
        print(manual_block(), file=sys.stderr)
        sys.exit(2)

    tmp = Path(tempfile.mktemp(suffix=".csv"))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as f, \
                tmp.open("wb") as out:
            shutil.copyfileobj(f, out)
        if not check_file(tmp):
            print("[DOWNLOAD] downloaded file failed the validity check - wrong format.", file=sys.stderr)
            tmp.unlink(missing_ok=True)
            print(manual_block(), file=sys.stderr)
            sys.exit(2)
        if SRC.exists():
            shutil.copy2(SRC, BACKUP)          # keep previous version as backup
        SRC.parent.mkdir(parents=True)
        shutil.move(str(tmp), str(SRC))
    except Exception as e:
        tmp.unlink(missing_ok=True)
        print(f"[DOWNLOAD] failed ({e}).", file=sys.stderr)
        print(manual_block(), file=sys.stderr)
        sys.exit(2)

    if check_file(SRC):
        print("[OK] New index file stored (previous version backed up as .bak).")
        return 0
    print("[ERROR] File not valid after copy.", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main("--force" in sys.argv[1:])
