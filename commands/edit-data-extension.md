---
description: Prune unused tabs from the project's Data Extension .xls, dedupe sample-data sets, and set Segment Name/General to the campaign name
argument-hint: [project-folder-path]
---

# /edit-data-extension

The Data Extension `.xls` shipped in `EMC_SAMPLE_MMDDYY/assets/` has **22 tabs** — a mix of test DEs (different personalization variants), seed-DE base, and per-LOB seed lists. Each remaining tab also ships with 3-5 duplicate sample sets (`SAMPLE_EMC_VALUE_MMDDYY`, `SAMPLE_EMC_VALUE2_MMDDYY`, …) and placeholder `Segment Name` / `Segment General` cell values. This command:

1. Prunes the tabs you don't need.
2. Drops the duplicate sample sets (`SAMPLE_EMC_VALUE2_MMDDYY` and higher), leaving only the original `SAMPLE_EMC_VALUE_MMDDYY` rows.
3. Renames the `Segment Name` cells to the campaign name (the `.xls` filename stem) and the `Segment General` cells to the campaign name with the trailing `_MMDDYY` stripped.

## Tab inventory (current scaffold)

```
TEST_DE_R1_R2-NoPersonalization     <- pick one TEST_DE_R1_R2 based on personalization needs
TEST_DE_R1_R2-Personalization
TEST_DE_R1_R2-FNameAndOffice

TEST_DE_DEV-FirstName-REF-ONLY      <- REF-ONLY: keep only if you're building from one of these specs
TEST_DE_DEV-APQNoMulti-REF-ONLY
TEST_DE_DEV-APQMulti-REF-ONLY
TEST_DE_DEV-HPQfields-REF-ONLY

SEED_DE-BaseRequiredForAll          <- always keep
SEED_DE-AllSeed                     <- keep if "All seed" was selected in intake

SEED_DE-AAAhighlights               <- per-LOB seed lists, keep the one(s) matching the project LOB
SEED_DE-ARC
SEED_DE-AutoBuying
SEED_DE-CreditCard
SEED_DE-Discounts
SEED_DE-eVia
SEED_DE-INSA
SEED_DE-INSL_INSP
SEED_DE-ProtectMyID
SEED_DE-Membership
SEED_DE-Retail
SEED_DE-SmartHome
SEED_DE-Travel
```

## Step 1 — Find the .xls

If `$1` is provided, treat it as the project folder. Otherwise use the current working directory if it's under `E:\Lumenalta\AAA SFMC Files\<YEAR>\`. Look for `<project>/assets/<project>.xls` (renamed during `/new-project`) or `<project>/assets/EMC_SAMPLE_MMDDYY.xls` (unrenamed scaffold).

If neither exists, stop and tell the user the project folder doesn't appear to contain an `assets/*.xls`.

## Step 2 — Show actual tabs

Run:

```
py .claude/scripts/de_tabs.py list "<path-to-xls>"
```

Show the user the current tab list. Don't assume the canonical 22 — the user may have already pruned.

## Step 3 — Ask which to keep

Use `AskUserQuestion` with **multiSelect: true**. List the actual tabs. Recommend a default set based on the intake's `LOB/Product` and the `seed_list` value (from `/new-project`'s parse output if available):

- Always pre-check `SEED_DE-BaseRequiredForAll`
- Pre-check `SEED_DE-AllSeed` if the intake's `seed_list` mentions "All"
- Pre-check the LOB-matching `SEED_DE-<LOB>` tab (Travel → `SEED_DE-Travel`, etc.)
- Pre-check **one** `TEST_DE_R1_R2-*` based on what the user says about personalization (no personalization / first-name only / first-name+office)
- Leave all `*-REF-ONLY` tabs unchecked unless the user explicitly wants them

Confirm the final keep-list with the user before deleting. **Refuse to proceed if the keep-list is empty** — Excel needs at least one sheet.

## Step 4 — Prune

```
py .claude/scripts/de_tabs.py keep "<path-to-xls>" "<tab1>" "<tab2>" ...
```

Each tab name must be quoted (some contain spaces — e.g. `"TEST_DE_DEV-FirstName-REF-ONLY "` has a trailing space, which is real). The script saves the file back in-place as Excel 97-2003 `.xls` (format 56).

This requires Excel to be installed on the machine (it drives Excel via COM). If pywin32 / Excel is unavailable, the script will error out — surface that error to the user.

## Step 5 — Dedupe sample sets + set Segment Name / Segment General

Derive the **campaign name** from the `.xls` filename stem (e.g. `EMC_BRAE_EML_CAM_ENG_PVEVENT_060826.xls` → `EMC_BRAE_EML_CAM_ENG_PVEVENT_060826`). The **Segment General** value is the campaign name with the trailing `_MMDDYY` stripped (regex: `_\d{6}$`). If the stem doesn't end with `_MMDDYY`, leave Segment General equal to the full stem.

Show the user a single confirmation preview:

```
Will apply to the remaining N tab(s):
  • Delete rows where Segment Name matches SAMPLE_EMC_VALUE<digit>_MMDDYY (e.g. SAMPLE_EMC_VALUE2_MMDDYY, SAMPLE_EMC_VALUE3_MMDDYY).
    Original SAMPLE_EMC_VALUE_MMDDYY rows and any non-sample rows are preserved.
  • For all surviving data rows: set Segment Name = <campaign>, Segment General = <campaign-without-trailing-_MMDDYY>.
```

Use `AskUserQuestion` with Yes / Skip / Cancel. Default = Yes. If the user picks Skip, stop after the tab prune (Step 4) and report what was done. If Cancel, undo nothing (the prune already happened) and exit.

If confirmed:

```
py .claude/scripts/de_tabs.py finalize "<path-to-xls>" "<campaign-name>"
```

This opens Excel via COM once, applies both edits across every remaining tab, and saves back as `.xls` (format 56). The script prints a per-tab summary of how many rows were deleted vs updated.

## Step 6 — Verify

Re-run `list` to confirm the resulting tab list and print it to the user along with the dedupe/rename summary from Step 5.

## Don'ts

- Do not edit cell values other than Segment Name (col A) and Segment General (col B). Everything else (test data, seed emails, office data) the user fills in manually.
- Do not convert the file to `.xlsx` — SFMC's Data Extension upload expects `.xls`.
- Do not delete every tab — Excel requires at least one to remain.
- Do not silently skip the confirmation. The user might want to keep extra tabs (e.g. for a multi-LOB send) or skip the dedupe/rename for an unusual project.
- Do not run `finalize` if the `.xls` filename still has the placeholder stem `EMC_SAMPLE_MMDDYY` — that means `/new-project` was never run and the campaign name would propagate as `EMC_SAMPLE_MMDDYY` into every row. Bail out with a clear error.
