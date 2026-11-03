---
description: Pre-R1 QA of a built email — Jira/Figma/HTML/test-send checks, writes qa-report.pdf and a pre-filled R1 QA Checklist
argument-hint: [project-folder] [--r1] [--offline] [--no-validate]
allowed-tools: Bash(python:*), Bash(python3:*), Bash(py:*), PowerShell(python:*), PowerShell(python3:*), PowerShell(py:*), Read, Write, Glob, Grep
---

# /qa-email

You are running QA on a finished email build. QA is **read-only**: never edit the build HTML. If you find a fix, describe it in the report; the developer applies it.

Arguments: `$ARGUMENTS`
- First non-flag argument = project folder (default: current directory).
- `--r1` → write statuses to the **R1** column of the checklist (default: **Dev** column).
- `--offline` → skip all HTTP requests (link redirects, image loads).
- `--no-validate` → don't send the HTML to validator.w3.org. Validation is ON by default: every version is run through the Nu HTML Checker (the same service as validator.w3.org/nu, and it validates the CSS in `<style>` and `style=""` too). It validates the **build HTML from the project folder** (the base versions, i.e. `--html` + every `--version`), not the post-send/Inbox Monster HTML. AmpScript is stripped first. Only **errors** are flagged; errors matching `patterns` in `.claude/scripts/qa/validator_exceptions.json` are listed as known email exceptions. Warnings are ignored except the short `important_warnings` list, which shows as WARN, never FLAG.

Scripts live in `.claude/scripts/qa/`. Deps: `beautifulsoup4 requests pillow pypdf openpyxl` (optional: `playwright` for renders).

## Step 0 — Pick the Python command

Team machines differ: some have `python` on PATH, some only the `py` launcher, some `python3`. Before anything else, try these **in this order** and use the first that exits 0 — it proves both that the interpreter is real (not the Windows Store `python` stub) and that the deps are installed:

```
python  -c "import bs4, requests, PIL, pypdf, openpyxl"
py      -c "import bs4, requests, PIL, pypdf, openpyxl"
python3 -c "import bs4, requests, PIL, pypdf, openpyxl"
```
Use that command everywhere below — every `python …` line in this file means "the command picked here". If one of them runs but fails only on the import, tell the user to run `<that command> -m pip install beautifulsoup4 requests pillow pypdf openpyxl` and stop. If none runs at all, say Python 3 isn't installed and stop.

Status vocabulary used everywhere: **PASS** (verified), **FLAG** (definite issue), **WARN** (likely issue, a human should look), **MANUAL** (cannot be verified from what I was given — say exactly what's needed), **N/A**.
Never mark PASS on something you did not actually verify. Anything that depends on how a real email client renders is never PASS without an Inbox Monster screenshot of that client.

---

## Step 1 — Inventory inputs

Glob the project folder and report a short table of what was found / missing and which checks are downgraded to MANUAL as a result. Only stop if there is no HTML.

| Input | Where to look | Required? | If missing |
|---|---|---|---|
| Build HTML (with AmpScript) | `*.html` in project root / `build/` | **Yes** | stop |
| Other versions (A/B, segments) | other `*.html` | no | A/B diff skipped |
| Jira export | `*.doc` / `*.docx` / `*.html` from Jira | strongly | subject/preheader/URLs/campaign become MANUAL |
| Figma PDF | `*.pdf` (same export `/generate-projectmiddle01` uses) | strongly | copy diff + 1:1 review become MANUAL |
| Inbox Monster previews export | `qa/*.zip` (Rendering report → ⋯ → **Export Previews**) | for rendering checks | all rendering/dark-mode/font/emoji checks MANUAL |
| Inbox Monster HTML | `qa/*.html` (Rendering report → ⋯ → **Download the HTML Content**) | recommended | tracked links + post-send size downgraded |
| Test send | `qa/*.eml` | optional | only adds From name + List-Unsubscribe headers on top of the IM HTML |
| Loose screenshots | `qa/screens/*.png` | optional | — |
| SFMC screenshots | `qa/screens/sfmc-*.png` (send definition / journey / A-B test config) | optional | send date + A/B setup MANUAL |
| Accuracy chart | `*accuracy*.xlsx` / `.pdf` | optional | header/footer URL accuracy MANUAL |
| Checklist template | `.claude/templates/R1 QA Checklist.xlsx` | for the xlsx output | skip xlsx, report only |

Create `qa/` in the project folder if it doesn't exist, plus a scratch folder `qa/.work/`.

**Deliverables vs. scratch files.** The developer only ever opens `qa/qa-report.pdf` and the checklist `.xlsx`, so those are the only files this command leaves behind (along with the inputs the user dropped in `qa/` and the unzipped `qa/screens/`). Everything the scripts pass between each other — `expected.json`, `qa_results*.json`, `checklist_results.json`, and the report's `qa-report.md` source — goes in `qa/.work/` and is deleted in Step 6 once the PDF and xlsx exist. On Windows `.json` often opens in an unrelated app (e.g. After Effects), so never point the developer at a JSON file; every finding belongs in the report or the checklist.

**Inbox Monster export zip:** unzip it into `qa/screens/` (Python `zipfile`, don't overwrite existing files). Map each image to a client from its filename (gmail / android / iphone / ios / apple mail / outlook / yahoo, and dark / light). Print the mapping; any image you can't map, look at it before guessing. The three required clients are Android Gmail, iOS Mail and Chrome Gmail — say which are missing.

## Step 2 — Expected values from the Jira export

1. `python .claude/scripts/qa/email_qa.py doc-text "<jira file>"` (Jira's Word export is HTML underneath; this flattens it to `field | value` lines).
2. Map fields **the same way `/new-project` does** — read `.claude/commands/new-project.md` for the field names it uses, so both commands agree on the source of truth.
3. Write `qa/.work/expected.json` (omit keys you can't find — don't guess):

```json
{
  "campaign_name": "", "subject": "", "preheader": "", "from_name": "",
  "send_date": "YYYY-MM-DD",
  "ab_test": false, "ab_variants": {"A": "...", "B": "..."},
  "business_unit": "AAA MWG | A3 Smart Home",
  "data_spec": "Engage | MIF",
  "header_cta": "My Account | Join AAA",
  "bread_legal": false,
  "utm": {"utm_source": "", "utm_medium": "", "utm_campaign": ""},
  "urls": [{"label": "Hero CTA", "url": "https://...full tagged URL..."}],
  "legal_required": ["exact disclaimer snippets the ticket requires"]
}
```
Only put a key in `utm` if it is the same on every body link; per-link values belong in `urls`.

`data_spec` follows the same rule `/new-project` uses: `MIF` if the ticket mentions **Members in Force** or **MiF** anywhere (fields, free text, or Comments), otherwise `Engage`. Set it only for an `AAA MWG` single-send campaign. `campaign_name` matters more than usual here: the script checks `@SegmentName` against it, and `@SegmentGeneral` against it minus the trailing `_MMDDYY`.

## Step 3 — Deterministic checks

```
python .claude/scripts/qa/email_qa.py check --html "<build.html>" --expected qa/.work/expected.json \
  --figma "<figma.pdf>" [--sent-html "<qa/IM download.html>"] [--eml "<qa/test.eml>"] \
  [--version "<other.html>" ...] --out qa/.work/qa_results.json [--offline] [--no-validate]
```
Read the printed summary. Open `qa/.work/qa_results.json` only for the sections you need (`links`, `images`, `copy_blocks`, `redirects`) — don't dump the whole file or the whole HTML into context.

If `utm_qa_check.py` exists in the repo (Glob for it), also run it against the Jira URL list and fold its result into the URL check.

If Playwright is installed: `python .claude/scripts/qa/render.py "<build.html>" --outdir qa/renders`. If not, skip silently and note it.

## Step 4 — Judgment checks (this is where you add value over the script)

Work through these; for each, cite evidence (element, alt text, URL, screenshot name).

**Header / body / footer.** The header (SharedTop03) and footer (SharedBtm01 + legal + SharedBtm02) are shared modules, the same on every campaign. The script tags every link and image with `region` (`header` / `body` / `footer`) — use it, and apply these team rules:
- **Dark mode:** ignore anything in the header or footer — inverted blue footer, washed-out app/social icons, header bars, etc. are expected and accepted. Dark-mode findings are about **body** modules only.
- **Footer nav underline:** the footer nav (My Account, Contact Us, Find A Branch, Privacy Policy, Email Preferences, Unsubscribe) is not underlined by design — never flag it. The script exempts it (`footer_nav: true` on those links). Footer **legal** links (required legal “here”, emails, phone numbers, disclaimers) must still be underlined.
- **UTMs:** only body links are tracked. Header and footer URLs must carry **no** UTM parameters — that's correct, never flag it as missing. A header/footer link that *does* have UTMs in the build is a FLAG. Compare UTMs to the Jira URL table for body links only. (In post-send HTML the script follows SFMC's click redirect and drops what SFMC appends at send — `ajs_uid`, `activity_id`, and the trailing `utm_source=salesforce&utm_medium=email` — so judge on `dest`, not on those.)

1. **Copy diff triage** — go through `figma_copy` mismatches. Separate real copy errors (wording, punctuation, numbers, prices, dates, ®/™, superscript refs) from noise (Figma annotations, line-break differences, AmpScript-rendered text). Report only the real ones.
2. **Figma 1:1 visual** — Read the Figma PDF pages (desktop and mobile frames) and compare to `qa/renders/*` or Inbox Monster screenshots, module by module, top to bottom: module order, missing/extra modules, image content, button style/color, header & footer variant, obvious spacing/alignment/size differences. State that this is a visual comparison at screenshot resolution — differences of a few pixels need a human with an overlay.
3. **Alt text** — read the `images` inventory: does each alt describe the image / match the intake? Apply the checklist rules: only clickable images have underlined alt; alt color/size match surrounding live text (Blue copy on White/Sky20/Lime30/Cloud20; White on Blue/Red/Cerulean/Asphalt/Pewter/Slate; Yellow on Blue); icons = the number or "bullet" — **except** an icon may have `alt=""` when the text beside it has **both** a heading and body copy (e.g. icon + H3 + paragraph); an `alt=""` icon next to only a heading, or only a single body paragraph, is a FLAG (the script checks this and records `icon_alt_ok` per image — confirm against the screenshot when the layout is unusual); tel button = "Call"; mailto button = "Email"; 5-star graphic = "5 out of 5 stars"; H1 image alt = 36px Smart Medium / Arial Bold.
4. **Data Spec & segment names** — the `data_spec` check reads `ProjectAmpscript.amp` next to the build HTML (or the inline `%%[ … ]%%` header on a Standalone / Via build) and works out which `@EmailType` / `@BusinessUnit` branch runs. It FLAGs: a live `@SegmentName` / `@SegmentGeneral` that is empty or still `EMC_SAMPLE…` (nothing fills them from the DE anymore, so they must be set by hand on every send, single-send campaigns included); `@DataSpec` not `Engage` / `MIF` on an AAA MWG campaign, or not matching `expected.data_spec`; and an Engage branch still calling `_CmpgnDataSpecVars_010725` / `_081126`, which re-read Segment Name / General from the DE and overwrite the manual values. A name that's set but differs from the Jira campaign name is a WARN — confirm it isn't a deliberate per-segment name. If the result is MANUAL (`ProjectAmpscript.amp` not in the folder), open it and check the same things by hand.
5. **Personalization** — read the AmpScript blocks (Grep for `%%[` in the build). Check logic: fallbacks for empty fields, correct DE/attribute names vs the Jira ticket, subject-line personalization strings. If a `.eml` exists, confirm it rendered.
6. **Legal** — business name in the © line matches the business unit; required legal for that unit present; numbered disclaimers start with a full-size number + one space; footer legal links underlined and Smart Medium / Arial Bold.
7. **Rendering (only from `qa/screens/`)** — per screenshot, check: no mobile blue links (esp. iOS Gmail dark), dark-mode icon fills and legibility of body modules (header/footer excluded, see above), border-radius fallback consistency, Smart font weights in Apple Mail, Arial fallback keeps bold in Outlook, button borders, superscripts in Gmail, mobile image swaps, emoji glyphs. Name the screenshot for every finding.
8. **Show/hide** — if the `responsive` check lists desktop-hidden content, list those items so both versions get reviewed.

## Step 5 — Write `qa/.work/qa-report.md`

Keep it scannable:

```
# QA — <project> — <date>
Inputs: HTML ✓ · Jira ✓ · Figma ✓ · test send ✗ · IM screens ✗ · SFMC screens ✗
Result: N FLAG · N WARN · N MANUAL · N PASS

## Blocking (FLAG)
- [#9 URLs] Hero CTA missing target=_blank — <a> “Shop now” → https://…

## QA team spec (1–17)
| # | Check | Status | Evidence / what's needed |
(one row per spec item 1–17, in order; Inbox Monster rows 12a/12b/12c for Android Gmail / iOS Mail / Chrome Gmail)

## R1 checklist extras
| Section | Check | Status | Evidence |
(validators, AmpScript spaces, tracking pixel, impression regions, size, clipping, header copy, footer modules, etc.)

## Needs a human
- numbered list: exactly what to open and what to look at
```

Then render the PDF the team actually reads: `python .claude/scripts/qa/report_pdf.py qa/.work/qa-report.md --out qa/qa-report.pdf` → `qa/qa-report.pdf` (banner, count tiles, colored status badges, flagged rows tinted). It prints through headless Edge/Chrome — no extra installs. The converter understands exactly the structure above (title / `Inputs:` / `Result:` lines, `>` callout, `##` sections, pipe tables with a `Status` column, `- [#N Area] …` blocking items, numbered lists, `**bold**`, `` `code` ``), so keep the Markdown to that shape. If it reports no browser found, the styled `qa/qa-report.html` is left in place to print manually — say so in the reply.

Spec → script check mapping: 1 campaign · 2 subject · 3 preheader · 4 send_date · 5 ab · 6 ampscript + data_spec · 7 figma_copy + header_footer + images + your visual pass · 8 legal · 9 links / links_sent / phone_text · 10 unsubscribe · 11 images + your alt-text pass · 12 screenshots only · 13 responsive + renders · 14 dark_mode · 15 fonts · 16 responsive (mobile images) · 17 emoji.

## Step 6 — Pre-fill the checklist

1. `python .claude/scripts/qa/fill_checklist.py list --template ".claude/templates/R1 QA Checklist.xlsx"` to see the rows.
2. Write `qa/.work/checklist_results.json` as `{"rows": [{"match": …, "status": …, "note": …}]}`, one entry per row (statuses must be `Pass`, `Flagged`, `N/A`, or `""` for "needs a human"). Notes ≤ 2 lines, start MANUAL items with what's needed.
   Row `match` keys: `HTML + CSS validators` · `Ampscript inspected` · `Email matches Figma` · `Standard header present` · `Header copy is either` · `Header line of business` · `Coded copy matches` · `Phone numbers underlined` · `Clickable email text underlined` · `Footer legal links underlined` · `Numbered disclaimers` · `Only clickable images` · `Alt text color and size` · `Alignment considered` · `Icons have appropriate alt` · `Alt text matches the specified` · `Web URLs reviewed` · `No unencoded spaces` · `Redirect accuracy` · `Query string syntax` · `No UTMs in legal` · `open in a new tab` · `begin with https` · `Tel links formatted` · `Mailto links formatted` · `LOB footer present` · `Blue footer logo` · `Closing sentence business name` · `Stay connected with the app` · `Social app icons` · `Footer navigation present` · `Required legal present; link copy` · `Required legal present (Smart Home` · `Bread legal` · `Inbox Monster tracking pixel` · `Impression Region code` · `Items coded separately` · `No mobile blue links` · `Dark mode: icons` · `Border-radius` · `Smart web font weights` · `Arial fallback preserves bold` · `Button borders display` · `Superscript size` · `Chrome Yahoo` · `Code gradients` · `Inbox Monster Custom QA` · `Total message size` · `Spam Assassin` · `Gmail clipping`
   - Inbox Monster-only rows (`Custom QA`, `Spam Assassin`, `Chrome Yahoo`, `Button borders` without a Mac Mail screenshot) → `""` with a MANUAL note.
   - Use `N/A` only when the email clearly doesn't contain the thing (e.g. no app icons module).
   - `Dark mode: icons` / dark-mode notes: body modules only — never mark Flagged for header/footer dark-mode appearance.
   - `Web URLs reviewed` / `Query string syntax`: header & footer links without UTMs are correct; Flagged only if a header/footer link carries UTMs or a body link differs from the Jira URL table.
   - `Ampscript inspected`: fold in the `data_spec` result — Flagged if it FLAGged (placeholder/empty segment names, wrong or missing `@DataSpec`, old `CmpgnDataSpecVars` call).
   - `Icons have appropriate alt`: Pass when every `alt=""` icon sits beside a heading + body copy; Flagged when any `alt=""` icon has only a heading or only body copy beside it.
3. `python .claude/scripts/qa/fill_checklist.py fill --template ".claude/templates/R1 QA Checklist.xlsx" --results qa/.work/checklist_results.json --out "qa/R1 QA Checklist - <project> - AUTO.xlsx" --column dev` (use `--column r1` if `--r1` was passed). The template is copied, never modified; findings go in a new "Auto-QA (Claude)" column G, yellow = needs a human.
4. **Clean up.** If `qa/qa-report.pdf` and the checklist xlsx were both written, delete `qa/.work/` (Python `shutil.rmtree`). If either failed, keep `qa/.work/` so the run can be finished by hand, and say so in the reply. Only ever delete `qa/.work/` — never the user's inputs in `qa/` or `qa/screens/`.

## Step 7 — Reply in chat

≤ 15 lines: the counts, the blocking flags (one line each), the top "needs a human" items, and the output paths (`qa/qa-report.pdf` first, then the checklist xlsx; if the PDF failed, point at the kept `qa/.work/qa-report.md` and `qa/qa-report.html` instead). Don't repeat the whole report.
