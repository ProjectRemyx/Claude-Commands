---
description: Bootstrap a new AAA MWG email project from an Email Intake Form .doc
argument-hint: [path-to-intake.doc]
---

# /new-project

Goal: take the user from "I have an Email Intake Form" to "I'm ready to edit `ProjectMiddle01.htm`" with one command. You handle the deterministic parts: copy the scaffold, rename files, pre-fill `ProjectAmpscript.amp` variables, drop in the legal copy.

## Inputs

The user may pass the intake `.doc` path as `$1`. If `$1` is empty, **always ask the user for the exact path** to the intake form they want to use. Do NOT auto-discover or default to anything in `Email_Intake_Form_Example/` — that folder contains examples and finished projects, not the active intake. The user is the source of truth for which intake drives this run.

The intake now arrives as a **Jira ticket export in Microsoft Word `.doc` format** (e.g. `DC-1185.doc`). Accept either a full path (`E:\...\DC-1185.doc`) or a drag-and-drop. Validate the path resolves to a `.doc` file before proceeding; if not, ask again.

## Step 1 — Parse the intake

Run the parser and capture its JSON output:

```
py .claude/scripts/parse_intake.py "<path-to-intake.doc>"
```

The parser reads the `.doc` via Word COM (`pywin32`), pulls the intake fields out of the Jira "Description" body (one `Label: value` per line — Jira metadata and the Comments section are ignored), and emits the same JSON shape as before: `raw` (verbatim field values), `derived` (campaign name + MMDDYY + year), `ampscript_proposed` (best-guess variable values), and `extras` (figma link, additional legal, send date).

Note: the parser already strips an `Email N:` prefix from journey subject/preview copy, maps `Discounts & Rewards`-style LOB names by contains-match, and blanks placeholder disclaimers (`see figma`, `N/A`, …) so they aren't treated as real legal copy. A single Jira ticket is usually **one email of a multi-email journey** (the siblings are separate tickets) — build the one named in `Campaign Name A` and let the user run the command again per ticket.

## Step 2 — Confirm with the user

Present a concise summary table of the proposed setup. Show **every value the user might want to override** before you write files:

- **New project folder**: `E:\Lumenalta\AAA SFMC Files\<YEAR>\<campaign_name>\`
- **Campaign / MMDDYY / Year** (from `derived`)
- **`@BusinessUnit`** (AAA MWG | A3 Smart Home)
- **`@MessageType`** (Marketing | Transactional) — this is a best-guess; always have the user confirm.
- **`@EmailType`** (Campaign | Journey | Triggered) — confirm carefully; "Journeys - Omnichannel, Triggered" in the intake usually means `Triggered`.
- **`@LOBHeader`** (must be one of: Auto Buying | Auto Glass | Auto Repair | Credit Card | Discounts | Insurance | Membership | AAA Smart Home Security | AAA Smart Business Security | Travel | No LOB Header)
- **`@LOBFooter`** (AAA.com | A3SmartHome.com | AAA.com/AutoBuying | AAA.com/AutoGlass | AAA.com/AutoRepair | AAA.com/Battery | AAA.com/DMV | AAA.com/Gift | AAA.com/IDTheft | AAA.com/Insurance | AAA.com/Life | AAA.com/Membership | AAA.com/MyMembership | AAA.com/MobileGlass | AAA.com/MVD | AAA.com/Renew | AAA.com/RenewToday | AAA.com/Repair | AAA.com/Smart | AAA.com/SmartBusiness | AAA.com/Travel | AAA.com/UpdateCard | Contact us at 1-877-363-6269 | Discounts) — the parser guesses based on LOB/Product but the intake doesn't always pin this down; ask.
- **`@LOBunsubscribe`** (Default | Highlights | Visa Credit Card | Auto and Other Vehicle Insurance | Auto Repair | Cyber Newsletter | Emergency and safety | Home and Other Property Insurance | Identity Protection | Life Insurance | Discounts and Benefits | Membership Newsletter | New Offers and Innovations | Smart Home | Travel | eVia)
- **`@SubjectLine`** — verify it has no straight quotes (`'` `"`), no HTML, no `&entities;`. If it does, suggest replacements (`'` `"` `"` `¹` `²` `³` `™`). Emojis are OK.
- **`@PreviewText`** — same straight-quote/HTML rules. Entities and emojis are OK.

Use `AskUserQuestion` for items with enumerated valid values when in doubt. For free-text fields (subject / preview) just ask for confirmation or an edit.

## Step 3 — Ask which HTML Email Block variant

The scaffold has two:

- **Standard** (`EMC_SAMPLE_MMDDYY.html`) — normal SFMC Content Block composition. Use for SFMC Engage/Journey/Triggered sends through Content Builder.
- **Standalone** (`EMC_SAMPLE_MMDDYY_NoPTSpacers_ViaHeatmaps_EngageDeployment_FilePassOffTo3rdPartyVendor_only.html`) — flattened CSS, no AMPscript wrapper, used for Via heatmaps, Dan's Engage deployments, or 3rd-party vendor file pass-offs.

Ask the user which one. Default to **Standard** if unspecified. Delete the unused variant from the new project folder. (If the user asks to keep both, leave both.)

## Step 4 — Create the project folder

Target path: `E:\Lumenalta\AAA SFMC Files\<YEAR>\<campaign_name>\`

`<YEAR>` comes from `derived.year` (parsed from the trailing `_MMDDYY` in the campaign name — NOT from today's date). If `<YEAR>` is empty, fall back to the current calendar year.

If the target folder already exists, **stop and ask** before overwriting — the user may already be partway through that project.

Copy the entire `EMC_SAMPLE_MMDDYY/` folder recursively to the target. PowerShell:

```powershell
Copy-Item -Recurse "E:\Lumenalta\AAA SFMC Files\BoilerplateV2\EMC_SAMPLE_MMDDYY" "E:\Lumenalta\AAA SFMC Files\<YEAR>\<campaign_name>"
```

### `assets/` must contain only the data file

The scaffold's `assets/` folder holds reference material that does **not** belong in a real project: subfolders of starting/test data (`Beginning of using Claude to edit test and seed DE List`, `Starting test data files A3 Smart Home BU`) and `ExampleSingle-SendDeploymentConfirmationScreenshot.png`. The new project's `assets/` keeps **only `EMC_SAMPLE_MMDDYY.xls`** from the root of that folder (renamed in Step 5).

After the copy, clear everything else out of the new `assets/`:

```powershell
$assets = "E:\Lumenalta\AAA SFMC Files\<YEAR>\<campaign_name>\assets"
Get-ChildItem -LiteralPath $assets -Directory | Remove-Item -Recurse -Force -Confirm:$false
Get-ChildItem -LiteralPath $assets -File | Where-Object { $_.Name -ne "EMC_SAMPLE_MMDDYY.xls" } | Remove-Item -Force -Confirm:$false
```

Only ever delete inside the **new project's** `assets/` — never touch `BoilerplateV2\EMC_SAMPLE_MMDDYY\assets\`. Verify the result is a single `.xls` before moving on.

## Step 5 — Rename files inside the new folder

The HTML Email Block file(s) must be renamed from `EMC_SAMPLE_MMDDYY*` to `<campaign_name>*`. The data extension `.xls` inside `assets/` should also be renamed to `<campaign_name>.xls`.

Use targeted `Rename-Item` calls (PowerShell). Do not blanket-rename anything — only files literally prefixed `EMC_SAMPLE_MMDDYY`.

## Step 6 — Edit `ProjectAmpscript.amp`

Open the new project's `ProjectAmpscript.amp` and update the variable values using `Edit` (find/replace on the `SET @X = '...'` lines). Variables to set:

- `@BusinessUnit`
- `@MessageType`
- `@EmailType`
- `@LOBHeader`
- `@LOBFooter` (only inside the `IF @IncludeLOBfooter == 'Y'` block)
- `@LOBunsubscribe` (only inside the `IF @BusinessUnit == 'AAA MWG'` branch)
- `@SubjectLine`
- `@PreviewText`
- `@SegmentName` and `@SegmentGeneral` — only set these in the Journey/Triggered branch or the A3 Smart Home Campaign branch. For `AAA MWG` + `Campaign`, leave them alone — they are populated by `CmpgnDataSpecVars` from the Data Extension.

**Leave `@ReviewRound = 'DEV'` as-is** — it's the test prefix and the user changes it manually per review round.

Do **not** put URLs inside variable values (except `@UnsubscribeURL`). If the user provides a project-specific URL, leave it for `ProjectMiddle01.htm`.

## Step 7 — `ProjectLegal.htm`: fill in the legal copy, then prune the scaffold

The scaffold ships every legal variant as an example. **Always prune it down to what this project actually uses** — leaving Lorem paragraphs and inapplicable conditionals behind is a defect, not a harmless leftover, and it eats into the 102 kB post-send budget.

### 7a. Place the copy

If `extras.additional_legal` is non-empty, put it in the scaffold's existing asterisk-footnote paragraph rather than appending a second one — the scaffold's first `<p>` (`*Lorem ipsum…`) is that slot. **Position it *below* the `FtrRequired01` `CONTENTBLOCKBYKEY` block**, so the standard "AAA email communication is intended for the benefit of AAA Members…" paragraph comes first.

If the intake has no extra legal, delete the asterisk paragraph too.

Numbered footnotes (`1 Lorem ipsum…`, `2 Lorem ipsum…`) pair with superscript references in body copy that doesn't exist yet at this stage — delete them. They can be copied back from `EMC_SAMPLE_MMDDYY/ProjectLegal.htm` when `ProjectMiddle01.htm` introduces a `<sup>`.

### 7b. Keep exactly these, delete the rest

Always keep:

- The opening Gmail-iOS comment, the `@IncludeFooterNavCol` table conditional, `<tr>` / `<td>`, and the `gmail-blend-screen` / `gmail-blend-difference` divs.
- The **AAA MWG required legal** block — `IF @BusinessUnit == 'AAA MWG' … IF @RequiredLegal == 'AAA MWG BU Default' … FtrRequired01_031425`.
- The **final two lines** — the `/* This p must remain at the bottom of this file and must remain open. Do not close. */` comment and the `<p class="white" style="margin:0 0 42px 0; …">` that follows it. `SharedBtm02` closes this `<p>` along with the divs, `<td>`, `<tr>`, and `<table>`, so the file must end with it unclosed and with no closing tags of its own.

Keep conditionally — **prompt the user before deleting either**, since re-adding means copying from the scaffold:

| Block | Keep when |
|---|---|
| `IF @SHSSBSLicenseLegal == 'Y'` → `FtrSHSLicForAAAMWG_011526` (SHS/SBS state licenses) | the project is for the **A3 Smart Home** business unit (or SHS/SBS security) |
| The Bread paragraph — "This message may be considered an advertisement or promotional message…" with the `REDIRECTTO(@UnsubscribeURL)` link | the project is a **credit card** email (rare) |

Default both to delete when `@BusinessUnit == 'AAA MWG'` and the campaign isn't a credit card email, but say so and let the user override. Note the Bread paragraph is *additional* to the blue footer's own UNSUBSCRIBE link (`@IncludeUnsubURL` / `@LOBunsubscribe`) — removing it does not remove the required unsubscribe.

Preserve the scaffold's tab indentation and don't reflow the lines you keep. Show the resulting file after pruning.

## Step 8 — Report

Print a tight summary:

- New project path
- Files renamed
- Variables set in `ProjectAmpscript.amp` (just the changed ones)
- `ProjectLegal.htm`: the legal copy placed, and which optional blocks were pruned vs. kept
- Reminders: `ProjectMiddle01.htm` is the next file to edit; `@ProjectFolderID` in the HTML Email Block still holds the scaffold's ID and must be updated once the Content Builder folder exists; the data extension `.xls` may need tab cleanup (`/edit-data-extension`); the Figma link from the intake is in `extras.figma_link`.

## Don'ts

- Do not introduce build tooling, package.json, or any new dependencies.
- Do not edit `GlobalModules/` or `BoilerplateV2_ExampleModules/`.
- Do not skip the confirmation step — the LOB→footer mapping and the EmailType (Triggered vs Journey) often need a human eye.
- Do not invent variable values outside the enumerated lists in `ProjectAmpscript.amp`'s inline comments.
