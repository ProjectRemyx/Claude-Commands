---
description: Bootstrap a new AAA MWG email project from an Email Intake Form .doc
argument-hint: [path-to-intake.doc]
---

# /new-project

Goal: take the user from "I have an Email Intake Form" to "I'm ready to edit `ProjectMiddle01.htm`" with one command. You handle the deterministic parts: copy the scaffold, rename files, pre-fill `ProjectAmpscript.amp` variables, drop in the legal copy.

One exception: a **Via Highlights** send has a fixed layout, so this command builds its body content too and there is no `ProjectMiddle01.htm` to hand off. That fork is gated on the Step 3a question — see [Via Highlights build](#via-highlights-build).

## Inputs

The user may pass the intake `.doc` path as `$1`. If `$1` is empty, **always ask the user for the exact path** to the intake form they want to use. Do NOT auto-discover or default to anything in `Email_Intake_Form_Example/` — that folder contains examples and finished projects, not the active intake. The user is the source of truth for which intake drives this run.

The intake now arrives as a **Jira ticket export in Microsoft Word `.doc` format** (e.g. `DC-1185.doc`). Accept either a full path (`E:\...\DC-1185.doc`) or a drag-and-drop. Validate the path resolves to a `.doc` file before proceeding; if not, ask again.

## Step 1 — Parse the intake

Run the parser and capture its JSON output:

```
py .claude/scripts/parse_intake.py "<path-to-intake.doc>"
```

The parser reads the `.doc` via Word COM (`pywin32`), pulls the intake fields out of the Jira "Description" body (one `Label: value` per line — Jira metadata and the Comments section are ignored), and emits the same JSON shape as before: `raw` (verbatim field values), `derived` (campaign name + MMDDYY + year, plus `is_ab_test` / `campaign_name_a` / `campaign_name_b`), `ampscript_proposed` (best-guess variable values), and `extras` (figma link, additional legal, send date).

Note: the parser already strips an `Email N:` prefix from journey subject/preview copy, maps `Discounts & Rewards`-style LOB names by contains-match, and blanks placeholder disclaimers (`see figma`, `N/A`, …) so they aren't treated as real legal copy. A single Jira ticket is usually **one email of a multi-email journey** (the siblings are separate tickets) — build the one named in `Campaign Name A` and let the user run the command again per ticket.

## Step 2 — Confirm with the user

Present a concise summary table of the proposed setup. Show **every value the user might want to override** before you write files:

- **New project folder**: `E:\Lumenalta\AAA SFMC Files\<YEAR>\<campaign_name>\`
- **Campaign / MMDDYY / Year** (from `derived`)
- **`@BusinessUnit`** (AAA MWG | A3 Smart Home)
- **`@MessageType`** (Marketing | Transactional) — this is a best-guess; always have the user confirm.
- **`@EmailType`** (Campaign | Journey | Triggered) — confirm carefully; "Journeys - Omnichannel, Triggered" in the intake usually means `Triggered`.
- **`@DataSpec`** (Engage | MIF) — only matters for `AAA MWG` + `Campaign`. Chosen automatically, no question asked: `ampscript_proposed.DataSpec` is `MIF` when the ticket mentions **Members in Force** or **MiF** anywhere (fields, free text, or Comments), otherwise `Engage`. Show the value, and when it's `MIF` quote `extras.data_spec_evidence` (the ticket lines that triggered it) so a false hit is easy to spot. Change it only if the user overrides it.
- **`@SegmentName` / `@SegmentGeneral`** — filled in automatically from `ampscript_proposed`: the campaign name, and the campaign name minus its trailing `_MMDDYY`. Show both values; no question needed. On an A/B test they come from **Campaign Name A** — `@SegmentName` is not variant-specific (`@ABVersion` appends the letter), so if the A name ends in a variant letter (`…_A_MMDDYY`), suggest dropping it.
- **`@LOBHeader`** (must be one of: Auto Buying | Auto Glass | Auto Repair | Credit Card | Discounts | Insurance | Membership | AAA Smart Home Security | AAA Smart Business Security | Travel | No LOB Header)
- **`@LOBFooter`** (AAA.com | A3SmartHome.com | AAA.com/AutoBuying | AAA.com/AutoGlass | AAA.com/AutoRepair | AAA.com/Battery | AAA.com/DMV | AAA.com/Gift | AAA.com/IDTheft | AAA.com/Insurance | AAA.com/Life | AAA.com/Membership | AAA.com/MyMembership | AAA.com/MobileGlass | AAA.com/MVD | AAA.com/Renew | AAA.com/RenewToday | AAA.com/Repair | AAA.com/Smart | AAA.com/SmartBusiness | AAA.com/Travel | AAA.com/UpdateCard | Contact us at 1-877-363-6269 | Discounts | AAA.com/CreditCards) — the parser guesses based on LOB/Product but the intake doesn't always pin this down; ask.
- **`@LOBunsubscribe`** (Default | Highlights | Visa Credit Card | Auto and Other Vehicle Insurance | Auto Repair | Cyber Newsletter | Emergency and safety | Home and Other Property Insurance | Identity Protection | Life Insurance | Discounts and Benefits | Membership Newsletter | New Offers and Innovations | Smart Home | Travel | eVia)
- **`@SubjectLine`** — verify it has no straight quotes (`'` `"`), no HTML, no `&entities;`. If it does, suggest replacements (`'` `"` `"` `¹` `²` `³` `™`). Emojis are OK.
- **`@PreviewText`** — same straight-quote/HTML rules. Entities and emojis are OK.
- **A/B test** — `derived.is_ab_test` (from the intake's `A/B Test: Yes|No` field). When it's `true`, also show:
  - **Campaign Name A / B** — `derived.campaign_name_a` and `derived.campaign_name_b`. The B name comes from the ticket's `Campaign Name B` field; when that field is blank the parser falls back to `<A>_B`, so **always have the user confirm the B name** — it becomes a filename and the SFMC Content Block name.
  - **Subject / preview per variant** — `raw.subject_line_b` / `raw.preview_text_b` (same content rules as A). If B's subject or preview differs from A's, this is a subject-line test and Step 6 has to branch them.
  - **`raw.ab_goal`** (A/B Test Goal & Description) — verbatim, so the user can confirm what actually differs between the variants.

Use `AskUserQuestion` for items with enumerated valid values when in doubt. For free-text fields (subject / preview) just ask for confirmation or an edit. The A/B answer is a Yes/No `AskUserQuestion` pre-selected from `derived.is_ab_test` — the field is sometimes left at `No` on a ticket that does describe a split, so confirm rather than trust it.

## Step 3 — Ask which HTML Email Block variant

The scaffold has two:

- **Standard** (`EMC_SAMPLE_MMDDYY.html`) — normal SFMC Content Block composition. Use for SFMC Engage/Journey/Triggered sends through Content Builder.
- **Standalone** (`EMC_SAMPLE_MMDDYY_NoPTSpacers_ViaHeatmaps_EngageDeployment_FilePassOffTo3rdPartyVendor_only.html`) — flattened CSS, no AMPscript wrapper, used for Via heatmaps, Dan's Engage deployments, or 3rd-party vendor file pass-offs.

Ask the user which one. Default to **Standard** if unspecified. Delete the unused variant from the new project folder. (If the user asks to keep both, leave both.)

If this is an A/B test, the variant picked here is the file that gets duplicated into an A copy and a B copy in [Step 5a](#step-5a--ab-test-two-html-email-blocks) — the choice is unchanged, there are just two of the chosen file.

### 3a. If Standalone — ask whether this is a Via Highlights send

Only when the user picked **Standalone**, ask one more question (`AskUserQuestion`, Yes / No):

> Is this a **Via Highlights** send?

**Always ask — never infer.** A `VIA_` campaign name is a strong hint, but Via also runs other single-file sends (one-off heatmap tests, vendor pass-offs) that are *not* Highlights, and Highlights is the only one with a fixed layout. Use the hint to pre-select the answer, not to skip the question.

- **No** → continue with Step 4 below as normal. The body gets authored later with `/generate-projectmiddle01`.
- **Yes** → **skip Steps 4–8 entirely** and follow [Via Highlights build](#via-highlights-build) instead. That path builds the body content in this same run, so `/generate-projectmiddle01` is not needed afterwards.

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

**If this is an A/B test, do Step 5a instead of the HTML rename** (the `.xls` rename is unchanged and still uses the A name).

## Step 5a — A/B test: two HTML Email Blocks

Only when the user confirmed **A/B test = Yes** in Step 2. Otherwise skip to Step 6.

An A/B test ships **two HTML Email Blocks in one project folder**, both pointing at the same `@ProjectFolderID` — so they share one `ProjectAmpscript`, one `ProjectMiddle01`, and one `ProjectLegal`. What separates them is a single new variable, `@email_version`, that the developer branches on to toggle whatever the test changes.

The project folder stays named after **Campaign Name A** (Step 4 is unchanged) — one folder, two files.

### Produce the two files

Copy the chosen variant from Step 3 twice, then delete the original:

```powershell
$proj = "E:\Lumenalta\AAA SFMC Files\<YEAR>\<campaign_name_a>"
$src  = "$proj\EMC_SAMPLE_MMDDYY.html"   # or the *_NoPTSpacers_... standalone, per Step 3
Copy-Item -LiteralPath $src "$proj\<campaign_name_a>.html"
Copy-Item -LiteralPath $src "$proj\<campaign_name_b>.html"
Remove-Item -LiteralPath $src -Force -Confirm:$false
```

Keep the chosen variant's filename suffix on both copies — a standalone A/B pair is `<campaign_name_a>_NoPTSpacers_..._only.html` / `<campaign_name_b>_NoPTSpacers_..._only.html`.

### Add `@email_version` to each file

In the opening `%%[ … ]%%` block, add **one line directly under `SET @ProjectFolderID`** — `'A'` in the A file, `'B'` in the B file. Nothing else in the file changes:

```
%%[/*
---------------------------------------------------------------------------
HTML Email Block
--------------------------------------------------------------------------- */
SET @BoilerplateFolderID = '399733'
SET @ProjectFolderID = '403609'
SET @email_version = 'A' /* A | B. A/B test variant, set per HTML Email Block. Branch on it in ProjectAmpscript / ProjectMiddle01 to toggle what differs between the variants. */
]%%
```

Placement matters: it must sit **above** the `CONTENTBLOCKBYKEY(… '_ProjectAmpscript')` call, because every downstream content block is evaluated after this line and can therefore read `@email_version`. Putting it anywhere else silently gives the shared blocks an empty variable.

`@email_version` is only ever `'A'` or `'B'` (or `'C'` / `'D'` if the ticket describes a 3- or 4-way split — then produce one file per letter, using the same rules). Never leave it empty in an A/B project, and never add it to a non-A/B project.

## Step 6 — Edit `ProjectAmpscript.amp`

Open the new project's `ProjectAmpscript.amp` and update the variable values using `Edit` (find/replace on the `SET @X = '...'` lines). Variables to set:

- `@BusinessUnit`
- `@MessageType`
- `@EmailType`
- `@DataSpec` — `'Engage'` or `'MIF'` per Step 2. Leave the line in place even when `@EmailType` isn't `Campaign`; it's only read inside the AAA MWG Campaign branch.
- `@LOBHeader`
- `@LOBFooter` (only inside the `IF @IncludeLOBfooter == 'Y'` block)
- `@LOBunsubscribe` (only inside the `IF @BusinessUnit == 'AAA MWG'` branch)
- `@SubjectLine`
- `@PreviewText`
- `@SegmentName` and `@SegmentGeneral` — **always set by hand, in every case, including single-send `AAA MWG` campaigns.** As of `CmpgnDataSpecVars_102826` the data spec no longer reads Segment Name / Segment General from the Data Extension, so the `SET` lines in the project are the only source. Replace the `'EMC_SAMPLE_MMDDYY'` / `'EMC_SAMPLE'` placeholders in the **branch that will actually run**:

  | `@EmailType` + `@BusinessUnit` | Branch to edit in the Data mapping section |
  |---|---|
  | `Campaign` + `AAA MWG` | the first `IF @BusinessUnit == 'AAA MWG'` block, above the `IF @DataSpec` conditional |
  | `Campaign` + `A3 Smart Home` | the `ELSEIF @BusinessUnit == 'A3 Smart Home'` block |
  | `Journey` / `Triggered` | the outer `ELSE` block |

  Values: `@SegmentName` = `ampscript_proposed.SegmentName` (the campaign name), `@SegmentGeneral` = `ampscript_proposed.SegmentGeneral` (the campaign name without its `_MMDDYY`). Leave the placeholders in the branches that don't run. `/qa-email` flags a live branch still holding `EMC_SAMPLE…`.

- **Leave the `IF @DataSpec` block's contents alone.** The `Engage` branch calls `_CmpgnDataSpecVars_102826` and the `MIF` branch maps `@FirstName` directly; never swap the Engage call back to `_010725` / `_081126` — those versions re-read Segment Name / Segment General from the DE and would overwrite the manual values.

**Standalone variant** (Step 3 = Standalone, not Via Highlights): the file has its own inline `SET @SegmentName = ''` / `SET @SegmentGeneral = ''` lines near the top. Fill those with the same two values — the standalone file never loads `ProjectAmpscript`, so leaving them empty blanks the test subject line's segment and the Inbox Monster tagging.

**Impression region name** (Standard variant): the HTML Email Block wraps `ProjectMiddle01` in `%%=BeginImpressionRegion("SegmentName")=%%`, where `"SegmentName"` is a literal placeholder, not a variable. Replace it with the actual `@SegmentName` value — `%%=BeginImpressionRegion("<campaign_name>")=%%` — so the region reports under the campaign instead of under the word `SegmentName`. Edit only the string inside the quotes; leave the `EndImpressionRegion(0)` line alone. On an A/B project make the same edit in **both** HTML Email Blocks, with the same `@SegmentName` value in each.

**Leave `@ReviewRound = 'DEV'` as-is** — it's the test prefix and the user changes it manually per review round.

### A/B test additions

`ProjectAmpscript` is shared by both HTML Email Blocks, so anything that differs per variant has to branch on `@email_version`. Two edits, both inside this one file:

1. **`@ABVersion`** — replace the literal with the variable:

   ```
   SET @ABVersion = @email_version
   ```

   Leave the scaffold's explanatory comment in place. `SubjectLineController` appends `_[Letter]` to the test subject line from `@ABVersion`; hard-coding `'A'` (or leaving it `''`) makes both variants' test subject lines identical, which is how a QA round loses track of which file it is reviewing. Ignore `ampscript_proposed.ABVersion` on an A/B project — it always proposes the `'A'` literal.

2. **`@SubjectLine` / `@PreviewText`** — only when B's differ from A's (Step 2 flagged this). Wrap them:

   ```
   IF @email_version == 'B' THEN
       SET @SubjectLine = '<subject line B>'
       SET @PreviewText = '<preview text B>'
   ELSE
       SET @SubjectLine = '<subject line A>'
       SET @PreviewText = '<preview text A>'
   ENDIF
   ```

   Both branches keep the Step 2 content rules — no straight quotes, no HTML, no `&entities;` in a subject line. If B's subject and preview match A's, leave the plain `SET` lines alone; the test is a creative test and gets branched in `ProjectMiddle01.htm` later.

Anything else the test changes (an image, a CTA label, a whole module) belongs in `ProjectMiddle01.htm` behind the same `IF @email_version == 'B'` conditional, authored later. Don't scaffold empty branches for it.

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
- **A/B test** (only when Yes): the two HTML Email Block filenames and the `@email_version` value in each, that both point at the same `@ProjectFolderID` and share one `ProjectAmpscript` / `ProjectMiddle01` / `ProjectLegal`, whether `@SubjectLine` / `@PreviewText` were branched or left common, and what the ticket says actually differs between the variants (`raw.ab_goal`) so the developer knows what still needs branching in `ProjectMiddle01.htm`
- Variables set in `ProjectAmpscript.amp` (just the changed ones) — always include `@DataSpec` (and, when `MIF`, the ticket line that triggered it) and the `@SegmentName` / `@SegmentGeneral` values plus which branch they were written into
- The impression region name set in the HTML Email Block (`BeginImpressionRegion("<campaign_name>")`)
- `ProjectLegal.htm`: the legal copy placed, and which optional blocks were pruned vs. kept
- Reminders: `ProjectMiddle01.htm` is the next file to edit; `@ProjectFolderID` in the HTML Email Block still holds the scaffold's ID and must be updated once the Content Builder folder exists (**in both files** on an A/B project); the data extension `.xls` may need tab cleanup (`/edit-data-extension`); the Figma link from the intake is in `extras.figma_link`.

---

# Via Highlights build

Reached only from Step 3a with **Standalone + Via Highlights = Yes**. Replaces Steps 4–8.

Via Highlights is a recurring newsletter with a **fixed layout**. Every issue reuses the same modules in the same order; what changes issue to issue is **images, copy, and URLs** (plus the footer's photo credits). So there is no variant-picking problem to solve here — the reference build is the spec, and the job is a slot-by-slot swap. That is why the `/generate-projectmiddle01` work folds into this run instead of being a second command.

**The reference build is `BoilerplateV2_ExampleModules/VIA_Highlights_072626_Snapshot.html`.** Read it before doing anything else. It is the base file for the project — *not* the scaffold's standalone variant, which lacks the Via navy header/footer and the Via-only mobile utility classes (`btn-mobile`, `hed-mobile`, `buttom-mobile-padding-small`, `buttom-btn-pad`, `padding-left-0`, `podcast-margin*`, `white-background-mobile`, `color-box-prehead`). Starting from the scaffold means rebuilding all of that by hand — don't.

## V1 — Get the creative

Ask the user to attach, in order of preference:

1. A **PDF export** of the issue — desktop **and** mobile if both exist.
2. Screenshots, one per section.

Then measure exactly as `/generate-projectmiddle01` Steps 2a/2b describe:

```
py .claude/scripts/parse_creative_pdf.py "<desktop.pdf>" --mobile "<mobile.pdf>"
```

and render 3–5× crops (`fitz.Matrix(3,3)` / `(5,5)`) per section to read copy verbatim and confirm weights. Extracted PDF text is unreliable (Type3 glyph artifacts) — **transcribe from the crops.**

You already have the intake's `campaign_urls` from Step 1. Re-read it now: `section` maps a row to a module by position, `type` is `Image` / `CTA Button` / `Text Link`, and `cell_instructions` is **alt text on `Image` rows** and **the visible label on link/button rows**. Read the ticket **Comments** too — reviewers flag wrong URLs and missing alt text there.

**If the user has no creative yet**: still do V2 and V3, then stop and report which slots are unfilled. Don't invent content to fill the structure.

## V2 — Create the folder, then swap in the snapshot as the base file

Folder rules are unchanged from Step 4: target `E:\Lumenalta\AAA SFMC Files\<YEAR>\<campaign_name>\`, `<YEAR>` from `derived.year` (the trailing `_MMDDYY`, **not** today's date), and **stop and ask if the folder already exists**. Campaign names follow `VIA_Highlights_MMDDYY`.

Copy the scaffold folder first (it carries `assets/` and `images/`), prune `assets/` to the single `.xls` and rename it, exactly as Steps 4–5 describe. Then make the snapshot the project's HTML file:

```powershell
$proj = "E:\Lumenalta\AAA SFMC Files\<YEAR>\<campaign_name>"
Copy-Item "E:\Lumenalta\AAA SFMC Files\BoilerplateV2\BoilerplateV2_ExampleModules\VIA_Highlights_072626_Snapshot.html" "$proj\<campaign_name>.html"
```

Then delete the files the single-file build never uses — **both** EMC_SAMPLE HTML variants plus `ProjectAmpscript.amp`, `ProjectMiddle01.htm`, `ProjectCSS.htm`, and `ProjectLegal.htm`. The Via build is one self-contained file: its AMPscript header, CSS, header, footer, and legal all live inside it, and those four content blocks would never be uploaded. List every deletion in the V6 report.

**Never edit the snapshot in place.** Read from `BoilerplateV2_ExampleModules/`; write only inside the new project folder.

### If the intake says A/B test

Rare on Highlights, but the rule is the same as [Step 5a](#step-5a--ab-test-two-html-email-blocks): copy the snapshot **twice**, to `<campaign_name_a>.html` and `<campaign_name_b>.html`, in the one folder named after Campaign Name A.

The difference is where the variable goes. This build has no `@ProjectFolderID` — its AMPscript header is the inline `%%[ … ]%%` block at the top of the file (snapshot lines 1–7) — so add `SET @email_version = 'A'` (resp. `'B'`) as the **first line of that block**, above `SET @ReviewRound`, and add `SET @ABVersion = @email_version` alongside it so `SubjectLineController` (called on line 8) labels each variant's test subject line with its letter.

Because a Via build is one self-contained file per variant with no shared content blocks, whatever the test changes — subject line, an image, a card's copy — is edited **directly in each file**. Don't wrap it in an `IF @email_version` conditional; there is nothing shared for the conditional to serve.

## V3 — Set the AMPscript header and the inline preview text

The file opens with a small `%%[ … ]%%` block (snapshot lines 1–7). Set:

| Variable | Value |
|---|---|
| `@ReviewRound` | leave `'DEV'` — the user changes it per review round |
| `@MessageType` | `'Marketing'` — **add this line; the snapshot omits it** (see below) |
| `@SegmentName` | the campaign name |
| `@SegmentGeneral` | the campaign name |
| `@SubjectLine` | from the intake |
| `@BodyBGcolor` | leave `'#E4E4E4'` — Via's grey body background, not the usual white |

**The missing `@MessageType` is a real defect in the snapshot, not a style choice.** `SharedIMAnlytcs`' inline block tests `IF @MessageType == 'Marketing'`; with the variable unset the comparison fails and the send silently tags itself with the **Transactional** Inbox Monster AutoTag CID. Via Highlights is a marketing newsletter, so insert `SET @MessageType = 'Marketing'` after `SET @ReviewRound` and say you did in the report.

Subject line and preview text keep the Step 2 content rules: no straight quotes, no HTML, no `&entities;` in `@SubjectLine`; entities and emojis fine in preview text; the SFMC **Preheader field stays blank**.

**Preview text is inline here, not in AMPscript** — it's the `<div class="preview-text">` at the top of `<body>`. Replace only the sentence at the front of that div and **leave the `&#8199;&#847;` and `&shy;` spacer run exactly as-is**, count included. It pushes inbox-preview snippets past the body copy; shortening it lets header text leak into the preview.

## V4 — Map the creative onto the Via module inventory

These are the six body modules in the reference build. Identify each section of the creative against this table, in order, before touching the file. Line numbers are into `VIA_Highlights_072626_Snapshot.html`.

| # | Module | Band | Identifying features | Snapshot lines |
|---|---|---|---|---|
| V-A | **Hero feature card** | sky-20 `#ccecf9` outer, `#E0EFF9` inner | Full-bleed **640×420** image (own mobile asset), then a white 590px card with `border-bottom-*-radius:15px`, `<h1>` 34px, 16px body paragraph, full-size CTA | 1052–1125 |
| V-B | **Sponsor / promo banner** | sits inside the sky-20 band, under a feature card | Single linked **590×200** image, `class="img-w-100"`, `padding:0 0 40px 0`. All copy is baked into the artwork | 1126–1138, 1448–1460 |
| V-C | **2-col article row** | white | **340×230** fully-rounded image left (`border-*-radius:15px` on all four corners) + `<h2>` 18px + small CTA right, in a 250px column; `<td class="mobile-hidden" style="width:10px">` gutter between | 1164–1223 |
| V-D | **2-col article row + eyebrow** | white | V-C plus an eyebrow `<h2>` above the headline — either `Advertisement` (12px, `#000000`, weight 500) or a section label like `Via Podcast` / `Podcast Question` (14px, **`#0070B9`**, weight 600) | 1292–1359, 1483–1549 |
| V-E | **Feature card + eyebrow** | sky-20 | V-A plus the `#0070B9` eyebrow above the `<h2>`; CTA label varies (`Listen Now`) | 1371–1447 |
| V-F | **2-up advertisement pair** | `#E0EFF9` | Two **282×190** rounded images side by side, `float:left` / `float:right` on 282px tables, split for Outlook by `<!--[if gte mso 9]></td><td align="right" valign="top" style="width:240px"><![endif]-->`; each with `Advertisement` eyebrow + `<h2>` + CTA | 1621–1748 |

Order in the reference issue: **V-A, V-B → V-C ×2, V-D(ad) → V-E, V-B → V-D ×2, V-F**, wrapped in `%%=BeginImpressionRegion("PrimaryNavigation")=%%` / `%%=EndImpressionRegion(0)=%%`.

Section count varies per issue. Duplicate or drop whole `<tr>` blocks to match the creative, keeping each band's `<!-- Content - <color> - 640px on desktop, 100% on mobile - Start/End -->` comments paired and the band alternation (sky-20 → white → sky-20 → white) intact.

**Fixed chrome — do not rebuild or restyle:** the navy Via header (Via logo 94×62, AAA logo 30×18, `My Account` + `View In Browser`, the 30px left/right blue bars), the SFMC tracking pixel, the Inbox Monster block, the impression-region wrappers, and the navy footer (AAA logo 105×63, app-store badges 108×36 / 121×36, four 37×37 social icons, the uppercase nav column, required legal, Via disclaimer, copyright).

### The type scale is the snapshot's, not the creative's

Via's approved scale **deliberately breaks the 1.5× line-height rule** in three places. Preserve these values verbatim; do not "correct" them, and do not re-derive sizes from the PDF measurements — the measurements are for confirming which module a section is, not for retyping the scale.

| Element | Desktop | Mobile class | Ratio |
|---|---|---|---|
| Feature card `<h1>` / `<h2>` | `font-size:34px; line-height:44px` bold | `font-size-28` | **1.29×** |
| Article row `<h2>` | `font-size:18px; line-height:26px` bold | `font-size-22` | **1.44×** |
| Feature card body `<p>` | `font-size:16px; line-height:26px` | `font-size-16` | **1.63×** |
| `#0070B9` section eyebrow | `font-size:14px; line-height:21px` weight 600 | `font-size-14` | 1.5× |
| `Advertisement` eyebrow | `font-size:12px; line-height:18px` weight 500 | `font-size-14` | 1.5× |
| Footer legal `<p>` | `font-size:12px; line-height:18px` | — | 1.5× |

Mobile is **larger** than desktop for the article `<h2>` (18→22) and both eyebrows (12/14→14). That inversion is intentional — the single-column mobile layout gets bigger type. `/generate-projectmiddle01` flags mobile > desktop as "unusual"; here it is correct, so don't raise it.

### When a section matches nothing in the table — ask, don't guess

This is the case the user flagged: an issue occasionally ends with a module that isn't in the reference build. Handle it exactly as `/generate-projectmiddle01` Step 4 handles a no-match — **say what you see and ask**, offering:

1. **Build it by hand** following the BoilerplateV2 table rules (all five `<table>` attributes, width in `style`, `w-100`/`w-90` on the inner table, `linear-gradient` pairs on inverted colors, MSO conditionals), naming the closest Via module so the user knows what it will resemble.
2. **Drop in a placeholder image** at the measured size — `https://fpoimg.com/<W>x<H>?text=…`. Often right for a Via ad slot, where copy is baked into the artwork. The tell is an image block with no live text lines over it.
3. **Something else** — a new shared module, or a question back to the designer.

Declare a **hybrid** too (e.g. V-C's row structure inside V-A's white card) rather than presenting it as a clean match.

Show the full mapping and any no-match question, then wait for approval before writing. Present it like `/generate-projectmiddle01` Step 6:

```
3. V-D  2-col article row + eyebrow — "Advertisement" / Travel Medford
   • Eyebrow: "Advertisement" — 12px/18 weight 500, mobile font-size-14
   • Headline: "Uncrowded. Unexpected. Unforgettable." — 18px/26 bold, mobile font-size-22
   • Image: 340x230, alt from campaign_urls section 3 "Image" row
   • CTA: "Explore Medford, Oregon"
   • href: advertiser URL from campaign_urls (no Via utm set — advertiser-supplied)
```

## V5 — Apply the swap

Only images, copy, URLs, and alt text change. Leave every `<table>`, class, `padding`, radius, gradient, MSO conditional, and `gmail-blend-*` wrapper alone.

- **Images** — replace `src` and set `width`/`height` to the module's fixed dimensions (640×420 / 590×200 / 340×230 / 282×190). Real hosted `image.emails.goaaa.com` URLs come from the asset team; if you don't have them, keep the snapshot's URLs and list every one in the report as still-placeholder.
- **Desktop/mobile image pairs** — V-A and V-E use **two different assets**: the desktop `<tr class="mobile-hidden">` at 640×420, and a hidden `<tr style="display:none" class="mobile">` holding a separate mobile crop at `width="0" height="0"` with `class="img-w-100"`. Both need the mobile asset's own URL. V-C and V-D reuse **one** asset in both rows. Don't collapse either pattern, and don't change `width="0" height="0"` on the hidden row.
- **Copy** — verbatim from the crops. Curly quotes (`'` `'` `"` `"`), `&nbsp;` for widow control only where the snapshot already uses it (`5 Best Airports in&nbsp;the&nbsp;West`), `&#8209;` for non-breaking hyphens.
- **`href`s** — paste verbatim from `campaign_urls`, with a **literal `&`** between params. `&amp;` inside an `href` is a bug. In a Via card, the image, the headline, the body copy, and the CTA all point at the **same destination**, differing only in `utm_content`: `img-<first words of alt>` / `txl-<first words of link text>` / `cta-<button label>`. Use that convention to *verify* you matched the right row to the right element — never to compose or edit a URL. Advertiser URLs (RAZ Mobility, Travel Medford, cruise/tour partners) don't carry the Via `utm` set at all; paste them as supplied.
- **Alt text** — from the `Image` row's `cell_instructions`, verbatim. Never author it, and never transcribe the words visible in the artwork. No matching row → `alt=""`, and list it in the report so wording can be collected in one pass. Header/footer logos, social icons, and app badges keep the alt they already have.
- **Footer, per issue** — update the **photo credits** paragraph (snapshot line 1872, `Photo credits: ©…`) from the creative or the ticket. Confirm the unsubscribe `list=` param matches the list being sent to (reference uses `list=AAA%20Highlights`). Leave the required-legal, Via disclaimer, and `%%xtyear%%` / `%%Member_*%%` copyright paragraphs untouched.
- **Legal / disclaimers** — Via legal lives inline in this file's footer. There is no `ProjectLegal.htm` on this path, so don't create one; if the intake carries extra legal copy, add it as a sibling `<p class="white" …>` above the copyright paragraph, matching the 12px/18 style.

Then verify before reporting:

```powershell
$f = "E:\Lumenalta\AAA SFMC Files\<YEAR>\<campaign_name>\<campaign_name>.html"
Select-String -Path $f -Pattern 'amp;' -AllMatches | Select-Object LineNumber, Line
(Get-Item $f).Length
```

Any `amp;` hit inside an `href` is the escaping bug — fix it. Total file size must stay under **102 kB** post-send (the reference build is ~120 kB on disk *with* its formatting whitespace; SFMC's rendered output is what counts, so flag it if the file grows materially against the reference rather than shrinking).

## V6 — Report

- New project path, the base file (`<campaign_name>.html`, copied from the snapshot — **both** files and their `@email_version` values if this is an A/B test), and every scaffold file deleted.
- The module sequence top-to-bottom with the band chain, so a dropped or duplicated band is obvious.
- AMPscript header values set — call out the added `SET @MessageType = 'Marketing'` explicitly.
- Preview text placed, and confirmation the spacer run is untouched.
- **URLs wired** — each element → its `utm_content`, plus any `campaign_urls` row with no matching element (usually a missed section) or element with no row. Note the `amp;` grep came back clean.
- **Alt text** — each image's `alt` and the row it came from; every image left `alt=""`.
- **Still placeholder** — image `src`s and any `href` with no row.
- Sections built by hand or as an FPO placeholder, and what the user chose for each.
- Footer photo credits updated; unsubscribe `list=` param confirmed.
- Any `[ILLEGIBLE — confirm]` copy.
- Reminders: the data extension `.xls` may need tab cleanup (`/edit-data-extension`); the pre-deploy checklist for an Engage send still applies — replace `@SubjectLine` with the final subject line, strip the AMPscript header, and make the Inbox Monster tracking static (see the comment header on the scaffold's standalone variant).

---

## Don'ts

These apply to both paths.

- Do not introduce build tooling, package.json, or any new dependencies.
- Do not edit `GlobalModules/` or `BoilerplateV2_ExampleModules/` — including `VIA_Highlights_072626_Snapshot.html`, which is read-only reference.
- Do not skip the confirmation step — the LOB→footer mapping and the EmailType (Triggered vs Journey) often need a human eye.
- Do not invent variable values outside the enumerated lists in `ProjectAmpscript.amp`'s inline comments.
- Do not leave `@SegmentName` / `@SegmentGeneral` as the `EMC_SAMPLE…` placeholders (or empty, in a standalone file) in the branch that runs — no data spec fills them anymore.
- Do not create a second project folder for an A/B test. It is one folder, one `@ProjectFolderID`, two HTML Email Blocks — a second folder would fork `ProjectAmpscript` / `ProjectMiddle01` / `ProjectLegal` and the two variants would drift.
- Do not add `@email_version` to a project that isn't an A/B test, and do not leave it empty in one that is.
- Do not run the Via Highlights path off a guess. It is gated on the Step 3a question, and only on **Standalone**.
- Do not restyle the Via reference build. Images, copy, URLs, alt text, and photo credits change; structure and type scale do not.
