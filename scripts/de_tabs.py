"""List, prune, or finalize tabs in an SFMC Data Extension .xls file.

The data-extension workbook is the old Excel 97-2003 .xls binary format.
Modern Python libs (openpyxl) can't write it. We use:

  - xlrd (2.0.1) for read-only listing
  - Excel COM via pywin32 for tab deletion and cell edits (requires Excel installed)

Usage:
    py .claude/scripts/de_tabs.py list <path-to.xls>
    py .claude/scripts/de_tabs.py keep <path-to.xls> <tab1> <tab2> ...
    py .claude/scripts/de_tabs.py finalize <path-to.xls> <campaign-name>

`keep` deletes every tab NOT named in the keep-list.

`finalize` operates on every remaining tab and (a) deletes data rows whose
Segment Name (col A) matches ^SAMPLE_EMC_VALUE\\d+_MMDDYY$ — i.e. the
duplicate sample sets SAMPLE_EMC_VALUE2_MMDDYY, _3_, _4_, _5_ — then
(b) sets every remaining data row's Segment Name to <campaign-name>
and Segment General to <campaign-name> with a trailing _DDDDDD stripped.
The original SAMPLE_EMC_VALUE_MMDDYY rows (no digit after VALUE) and any
real data rows are preserved.

All commands save the file back in-place as .xls (Excel format 56).
"""
import re
import sys
from pathlib import Path


SAMPLE_DUP_RE = re.compile(r"^SAMPLE_EMC_VALUE\d+_MMDDYY$")
TRAILING_DATE_RE = re.compile(r"_\d{6}$")


def cmd_list(path: Path) -> None:
    import xlrd
    wb = xlrd.open_workbook(str(path))
    for name in wb.sheet_names():
        print(name)


def _open_excel():
    """Return (excel, cleanup) — caller must call cleanup() in finally."""
    import win32com.client as win32
    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False  # suppress "are you sure" on tab/row delete
    return excel


def cmd_keep(path: Path, keep: list[str]) -> None:
    if not keep:
        raise SystemExit("ERROR: keep-list is empty; refusing to delete every tab")

    abs_path = path.resolve()
    excel = _open_excel()
    try:
        wb = excel.Workbooks.Open(str(abs_path))

        existing = [sh.Name for sh in wb.Sheets]
        missing = [k for k in keep if k not in existing]
        if missing:
            raise SystemExit(
                f"ERROR: these requested tabs do not exist in the workbook: {missing}\n"
                f"Existing tabs: {existing}"
            )

        keep_set = set(keep)
        for name in list(existing):
            if name in keep_set:
                continue
            wb.Sheets(name).Delete()

        wb.SaveAs(str(abs_path), FileFormat=56)
        wb.Close(SaveChanges=False)
    finally:
        excel.Quit()

    print(f"OK: kept {len(keep)} tabs in {abs_path.name}")


def cmd_finalize(path: Path, campaign: str) -> None:
    """Dedupe SAMPLE_EMC_VALUE2+ rows and rename Segment Name/General across all tabs.

    Surgical edits via Excel COM — only column A (Segment Name) and column B (Segment General)
    are modified. The other 32 columns (Member Number, Office data, etc.) are never read or
    written, so text-formatted numbers like 16-digit member numbers cannot lose precision
    via float coercion.

    For each remaining sheet:
      1. Walk col A bottom-up. Any row where col A matches ^SAMPLE_EMC_VALUE\\d+_MMDDYY$
         (e.g. SAMPLE_EMC_VALUE2_MMDDYY) is deleted as a duplicate sample set.
      2. Walk the surviving rows top-down. Any row with a non-empty col A gets:
            col A := campaign
            col B := campaign with a trailing _DDDDDD stripped
      3. Header row (row 1) and blank rows are left alone.
    """
    if not campaign:
        raise SystemExit("ERROR: campaign name is required")

    general = TRAILING_DATE_RE.sub("", campaign)
    abs_path = path.resolve()
    excel = _open_excel()
    summary: list[tuple[str, int, int]] = []  # (sheet, deleted, updated)

    try:
        wb = excel.Workbooks.Open(str(abs_path))

        for sh in wb.Sheets:
            used = sh.UsedRange
            last_row = used.Row + used.Rows.Count - 1
            if last_row < 2:
                summary.append((sh.Name, 0, 0))
                continue

            # Phase 1: delete duplicate-sample rows bottom-up so indices stay valid.
            deleted = 0
            for r in range(last_row, 1, -1):
                v = sh.Cells(r, 1).Value
                if v is None:
                    continue
                if SAMPLE_DUP_RE.match(str(v)):
                    sh.Rows(r).Delete()
                    deleted += 1

            # Phase 2: rewrite Segment Name + Segment General on surviving data rows.
            used = sh.UsedRange
            last_row = used.Row + used.Rows.Count - 1
            updated = 0
            for r in range(2, last_row + 1):
                v = sh.Cells(r, 1).Value
                if v is None or str(v).strip() == "":
                    continue
                sh.Cells(r, 1).Value = campaign
                sh.Cells(r, 2).Value = general
                updated += 1

            summary.append((sh.Name, deleted, updated))

        wb.SaveAs(str(abs_path), FileFormat=56)
        wb.Close(SaveChanges=False)
    finally:
        excel.Quit()

    print(f"OK: finalized {abs_path.name} (campaign={campaign!r}, segment_general={general!r})")
    for name, deleted, updated in summary:
        print(f"  - {name}: deleted {deleted} duplicate-sample row(s), updated {updated} segment row(s)")


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    action = sys.argv[1]
    path = Path(sys.argv[2])
    if not path.is_file():
        print(f"ERROR: {path} does not exist", file=sys.stderr)
        sys.exit(1)

    if action == "list":
        cmd_list(path)
    elif action == "keep":
        cmd_keep(path, sys.argv[3:])
    elif action == "finalize":
        if len(sys.argv) < 4:
            raise SystemExit("ERROR: finalize requires a campaign name argument")
        cmd_finalize(path, sys.argv[3])
    else:
        print(f"ERROR: unknown action {action!r}; expected 'list', 'keep', or 'finalize'", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
