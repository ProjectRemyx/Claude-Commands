#!/usr/bin/env python3
"""
fill_checklist.py — write /qa-email results into a COPY of the R1 QA Checklist .xlsx.

  python fill_checklist.py list   --template "R1 QA Checklist.xlsx"
  python fill_checklist.py fill   --template "R1 QA Checklist.xlsx" --results checklist_results.json \
                                  --out "qa/R1 QA Checklist - <project> - AUTO.xlsx" [--column dev|r1]

checklist_results.json:
{
  "project_name": "...", "developer": "...",            (optional, fill the header block)
  "rows": [ {"match": "Phone numbers underlined", "status": "Pass|Flagged|N/A|", "note": "..."} ]
}
`match` is a case-insensitive substring of the Check text (column B). Empty status = left for a human;
the note still goes in the new "Auto-QA" column G. The template is never modified.
"""
import argparse, json, shutil, sys
from copy import copy
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

VALID = {"Pass", "Flagged", "N/A", ""}


def find_header(ws):
    for row in ws.iter_rows(min_col=2, max_col=6):
        if row[0].value == "Check" and row[1].value == "Dev":
            return row[0].row
    return None


def check_rows(ws):
    out = []
    for r in range(1, ws.max_row + 1):
        b, e = ws.cell(r, 2).value, ws.cell(r, 5).value
        if b and e in ("Yes", "No"):
            out.append((r, str(b), e))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["list", "fill"])
    p.add_argument("--template", required=True)
    p.add_argument("--results")
    p.add_argument("--out")
    p.add_argument("--column", choices=["dev", "r1"], default="dev")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if a.cmd == "list":
        ws = load_workbook(a.template).active
        for r, b, e in check_rows(ws):
            print(f"{r:>3} [{e:3}] {b}")
        return

    res = json.load(open(a.results, encoding="utf-8"))
    shutil.copyfile(a.template, a.out)
    wb = load_workbook(a.out)
    ws = wb.active
    col = 3 if a.column == "dev" else 4
    rows = check_rows(ws)

    # new Auto-QA column G, styled like the existing headers
    ws.column_dimensions["G"].width = 70
    for r in range(1, ws.max_row + 1):
        if ws.cell(r, 2).value == "Check" and ws.cell(r, 3).value == "Dev":
            h = ws.cell(r, 7, "Auto-QA (Claude)")
            src = ws.cell(r, 6)
            h.font, h.fill, h.alignment = copy(src.font), copy(src.fill), copy(src.alignment)
            h.border = copy(src.border)

    if res.get("project_name"):
        ws["C5"] = res["project_name"]
    if res.get("developer"):
        ws["C6"] = res["developer"]

    unmatched, used = [], set()
    for item in res.get("rows", []):
        status = item.get("status", "") or ""
        if status not in VALID:
            sys.exit(f"Invalid status {status!r} for {item['match']!r} — use Pass / Flagged / N/A / empty")
        hits = [r for r, b, _ in rows if item["match"].lower() in b.lower()]
        if not hits:
            unmatched.append(item["match"]); continue
        r = hits[0]
        used.add(r)
        if status:
            ws.cell(r, col, status)
        note = item.get("note", "")
        if note:
            c = ws.cell(r, 7, note)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.font = Font(size=9, color="9C0006" if status == "Flagged" else "333333")
            if not status:
                c.fill = PatternFill("solid", fgColor="FFF4CC")  # yellow = needs a human
    wb.save(a.out)
    skipped = [b for r, b, _ in rows if r not in used]
    print(f"Wrote {a.out}  ({len(used)} rows filled in the {a.column.upper()} column)")
    if unmatched:
        print("No row matched:", "; ".join(unmatched))
    if skipped:
        print(f"{len(skipped)} checklist rows left untouched (no result supplied)")


if __name__ == "__main__":
    main()
