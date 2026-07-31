# Claude-Commands

This repository holds all Claude Commands that the Lumenalta team for AAA MWG can reference and pull for updates.

These are custom [Claude Code](https://claude.com/claude-code) slash commands that automate the deterministic parts of building an SFMC email for the **AAA Mountain West Group (MWG)** and **A3 Smart Home** business units — bootstrapping a project from a Jira intake ticket, translating a Figma creative into `ProjectMiddle01.htm`, and cleaning up the Data Extension workbook.

## Contents

```
commands/
  new-project.md                 -> /new-project
  generate-projectmiddle01.md    -> /generate-projectmiddle01
  edit-data-extension.md         -> /edit-data-extension
scripts/
  parse_intake.py                Jira .doc intake -> JSON
  parse_creative_pdf.py          Figma PDF export -> measured type + background metrics
  de_tabs.py                     Data Extension .xls tab prune / dedupe / rename
```

## Installing

The commands expect to run from inside `BoilerplateV2`, and they call the helper scripts by the relative path `.claude/scripts/<script>.py`. Copy both folders from this repo into `BoilerplateV2\.claude\`:

```
BoilerplateV2\.claude\commands\   <- commands/ from this repo
BoilerplateV2\.claude\scripts\    <- scripts/ from this repo
```

`.claude\settings.local.json` is machine-specific and is not part of this repo — leave your existing one in place.

Restart Claude Code (or start it in `BoilerplateV2`) and the three slash commands will be available. Pull this repo when you want the latest versions.

## Typical workflow

```
1. /new-project <intake.doc>          scaffold the project folder + ProjectAmpscript + ProjectLegal
2. /generate-projectmiddle01          measure the creative, stitch and spec ProjectMiddle01.htm
3. /edit-data-extension               prune DE tabs, dedupe sample sets, set Segment Name/General
```

Every command stops and asks for confirmation before it writes files. The LOB-to-footer mapping, `@EmailType` (Triggered vs. Journey), module variant choice, and the DE keep-list all need a human eye — none of them are reliably derivable from the intake alone.

---

## `/new-project [path-to-intake.doc]`

Takes you from "I have an Email Intake Form" to "I'm ready to edit `ProjectMiddle01.htm`".

The intake arrives as a **Jira ticket export in Microsoft Word `.doc` format** (e.g. `DC-1185.doc`). Pass the path as an argument or drag the file in; if you don't, the command asks. It never auto-discovers an intake — you are the source of truth for which ticket drives the run.

What it does:

1. **Parses the intake** via `parse_intake.py` — pulls the `Label: value` fields out of the ticket Description, ignoring Jira metadata and Comments.
2. **Confirms every value with you** before writing anything: target folder, campaign / MMDDYY / year, `@BusinessUnit`, `@MessageType`, `@EmailType`, `@LOBHeader`, `@LOBFooter`, `@LOBunsubscribe`, `@SubjectLine`, `@PreviewText`.
3. **Asks which HTML Email Block variant** — Standard (normal Content Block composition) or Standalone (flattened CSS, for Via heatmaps, Engage deployments, and 3rd-party vendor handoffs). Deletes the unused one.
4. **Creates the project folder** at `E:\Lumenalta\AAA SFMC Files\<YEAR>\<campaign_name>\` by copying `EMC_SAMPLE_MMDDYY/`, then strips the scaffold's reference material out of `assets/` so only the DE `.xls` remains.
5. **Renames** the HTML Email Block file(s) and the `.xls` from `EMC_SAMPLE_MMDDYY*` to the campaign name.
6. **Pre-fills `ProjectAmpscript.amp`** with the confirmed values.
7. **Fills in and prunes `ProjectLegal.htm`** — places the intake's additional legal below the `FtrRequired01` block, deletes the Lorem footnotes, and prunes the inapplicable conditional blocks (asking first, since re-adding means copying from the scaffold).

Notable guardrails:

- `<YEAR>` comes from the trailing `_MMDDYY` in the campaign name, **not** today's date.
- If the target folder already exists, it stops and asks — you may be partway through that project.
- Only ever deletes inside the **new** project's `assets/`, never the scaffold's.
- Leaves `@ReviewRound = 'DEV'` alone; you change that manually per review round.
- A single Jira ticket is usually **one email of a multi-email journey** — the siblings are separate tickets, so run the command again per ticket.

## `/generate-projectmiddle01 [project-folder-path]`

Turns a Figma creative into a specced `ProjectMiddle01.htm`. Attach a **PDF export** — desktop *and* mobile if both exist, which is what gives the exact responsive type scale. Screenshots work but sizes are then estimated; `.fig` files can't be opened.

1. **Measures the creative** with `parse_creative_pdf.py`: background bands with palette names, rounded cards, square inset panels, image bboxes, every text line's size / line-height / alignment / color, and the paired desktop↔mobile type scale with the matching `font-size-*` class.
2. **Renders high-zoom crops** for what measurement can't see — font weight, icon artwork, dividers, and the copy itself (extracted PDF text is corrupted by Figma's Type3 fonts, so copy is always transcribed from crops).
3. **Pulls the real tracking URLs** from the ticket's Campaign URLs table via `parse_intake.py`, matching rows to elements by section then label.
4. **Builds the background chain first** — one band = one top-level `<tr>` — because the band and card structure is what determines the module variant.
5. **Maps sections to modules** from `Modules_V3_Styles.html` (read first; it's the source of truth) and the other example files, choosing the variant on band + card + heading alignment.
6. **Proposes a numbered sequence** with the evidence for each variant, the copy, the type scale, and a list of weight/copy deltas vs. module defaults — then waits for your approval.
7. **Stitches and applies the spec**: copy, font sizes retyped to measured values, weights, alignment, background colors with their `linear-gradient` pairs, icon/image dimensions, button labels, alt text, and real `href`s.
8. **Reports** the final outline, background chain, type scale, URLs wired, alt text sourcing, and everything still left as a placeholder.

This command absorbed the old `/add-module`, which is no longer needed as a separate step — Step 7 does the same snippet extraction and table-markup validation inline.

Notable guardrails:

- The example modules' font sizes are **placeholders** — retyping them to the measured scale is the step that gets skipped most often, and it is not optional.
- `line-height` is always 1.5 × `font-size`, at both breakpoints. If the creative measures otherwise at a body/heading size, the creative is wrong.
- Alt text comes **verbatim** from the Campaign URLs table's `Cell Instructions` column, never authored and never transcribed from the artwork. No matching row means `alt=""`, reported so missing wording can be collected in one pass.
- URLs are pasted verbatim with literal `&` between params — an `&amp;` inside an `href` breaks SFMC's link wrapping.
- First-name personalization lives entirely in the `@FirstNameIntro*` AMPscript variable; the body contains only `%%=v(@FirstNameIntro)=%%`.
- A section with no reasonable module match is escalated, not forced — build by hand, drop an FPO placeholder image, or ask the designer.

## `/edit-data-extension [project-folder-path]`

The scaffold's Data Extension `.xls` ships with **22 tabs** (test DE personalization variants, REF-ONLY specs, the seed base, and per-LOB seed lists), each carrying 3–5 duplicate sample sets and placeholder Segment values. This command:

1. **Lists the actual tabs** via `de_tabs.py list` — never assumes the canonical 22, since you may have already pruned.
2. **Asks which to keep** (multi-select) with recommendations from the intake's LOB and seed-list: always `SEED_DE-BaseRequiredForAll`, `SEED_DE-AllSeed` if the intake says "All", the LOB-matching seed tab, and exactly one `TEST_DE_R1_R2-*` based on personalization needs. `*-REF-ONLY` tabs stay unchecked unless you ask.
3. **Prunes** via `de_tabs.py keep`.
4. **Dedupes and renames** via `de_tabs.py finalize` — deletes rows whose Segment Name matches `SAMPLE_EMC_VALUE<digit>_MMDDYY` (keeping the original `SAMPLE_EMC_VALUE_MMDDYY` rows), then sets Segment Name to the campaign name and Segment General to the campaign name with the trailing `_MMDDYY` stripped.
5. **Verifies** by re-listing the tabs.

Notable guardrails:

- Refuses an empty keep-list — Excel needs at least one sheet.
- Bails out if the `.xls` still has the placeholder stem `EMC_SAMPLE_MMDDYY`, which would propagate that name into every row.
- Only touches Segment Name (col A) and Segment General (col B); test data, seed emails, and office data are yours to fill in.
- Never converts to `.xlsx` — SFMC's DE upload expects `.xls`.

---

## Helper scripts

All three are called by the commands, but they run standalone too.

### `parse_intake.py`

```
py .claude/scripts/parse_intake.py <path-to-intake.doc>
```

Reads the Jira `.doc` export via Word COM and emits JSON on stdout:

| Key | Contents |
|---|---|
| `raw` | verbatim intake field values |
| `derived` | campaign name, MMDDYY, year |
| `ampscript_proposed` | best-guess `ProjectAmpscript.amp` variable values |
| `extras` | Figma link, additional legal, send date |
| `campaign_urls` | Campaign URLs table as `{placement, section, type, cell_instructions, url}` rows |

`section` comes from a `(section N)` prefix and matches the section order in the creative, so a URL maps straight to a module. `cell_instructions` does double duty: on an `Image` row it's the alt text; on a `CTA Button` / `Text Link` row it's the visible label.

Requires `pywin32` + Microsoft Word.

### `parse_creative_pdf.py`

```
py .claude/scripts/parse_creative_pdf.py DESKTOP.pdf
py .claude/scripts/parse_creative_pdf.py DESKTOP.pdf --mobile MOBILE.pdf
py .claude/scripts/parse_creative_pdf.py DESKTOP.pdf --mobile MOBILE.pdf --json
```

Also takes `--pages 1-3` for multi-page exports. Reports background bands (named against the AAA MWG palette), rounded cards, square inset panels, image bboxes, every text line's size / line-height / alignment / background / color, and — with `--mobile` — each string paired across breakpoints with the ready-to-paste inline style and matching `font-size-*` class.

Figma exports email frames at 640px (desktop) / 320px (mobile), so PDF points map 1:1 to CSS px. If the export width is neither, the script says so and prints the scale factor to apply.

Requires `pymupdf`.

### `de_tabs.py`

```
py .claude/scripts/de_tabs.py list     <path-to.xls>
py .claude/scripts/de_tabs.py keep     <path-to.xls> <tab1> <tab2> ...
py .claude/scripts/de_tabs.py finalize <path-to.xls> <campaign-name>
```

`list` is read-only (`xlrd`). `keep` and `finalize` drive Excel via COM and save back in-place as Excel 97-2003 format 56. Quote every tab name — some contain a real trailing space (e.g. `"TEST_DE_DEV-FirstName-REF-ONLY "`).

Requires `xlrd` 2.0.1 + `pywin32` + Microsoft Excel.

## Requirements

- **Python 3.12**, callable as `py`
- **Packages**: `pywin32`, `pymupdf`, `xlrd` 2.0.1, `xlwt`, `openpyxl`
- **Microsoft Word and Excel installed** — both `parse_intake.py` and `de_tabs.py` drive them over COM, so these commands are Windows-only
- Claude Code, run with `BoilerplateV2` (or a project folder under it) as the working directory

```powershell
py -m pip install pywin32 pymupdf xlrd==2.0.1 xlwt openpyxl
```
