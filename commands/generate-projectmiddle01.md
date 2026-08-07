---
description: Look at a Figma creative screenshot or PDF export and propose which BoilerplateV2_ExampleModules to stitch together
argument-hint: [project-folder-path]
---

# /generate-projectmiddle01

Goal: the user attaches one or more screenshots OR a PDF export of the Figma creative, you **measure** it section-by-section, propose a sequence of modules from `BoilerplateV2_ExampleModules/`, the user confirms, and you stitch them in — with the creative's real background colors, card structure, and font sizes applied.

**The four things this command gets wrong most often**, so check them explicitly every run:

1. **Picking the wrong variant of the right module family.** Nearly every V3 module exists in 3–5 variants that differ *only* by background band and whether there's an inset rounded card. Get the background chain right first (Step 3), then the variant follows.
2. **Leaving the example module's font sizes in place.** The example modules are a styling reference, not a spec. Their sizes are placeholders — you must retype them to the creative's measured sizes (Step 5).
3. **Stacking two modules and getting 60px of space between them.** Each module ships padding on both its top and its bottom because each is presented standalone. Adjacent modules must end up **30px apart on desktop / 20px on mobile** — zero the bottom padding on every module but the last (Step 3, applied in Step 7).
4. **Leaving example-asset image URLs in the build.** Every `<img src>` becomes an FPO placeholder carrying its own dimensions — `https://fpoimg.com/<W>x<H>?text=<W>x<H>` (Step 7). A real-looking photo from another campaign reads as a finished build in review.

## Not for Via Highlights

**Via Highlights sends are not built with this command.** Their layout is fixed, so `/new-project` builds the body inline when the user answers yes to its Step 3a question, working from `BoilerplateV2_ExampleModules/VIA_Highlights_072626_Snapshot.html`.

If you land here on a Via Highlights project anyway — the file is a single standalone `VIA_Highlights_MMDDYY.html` with the navy Via header and footer inline, and no `ProjectMiddle01.htm` — **stop and follow the "Via Highlights build" section of `.claude/commands/new-project.md` instead** (steps V4–V5 cover the module inventory and the slot-by-slot swap). Do not apply Steps 3–5 below to it: the background-chain and variant logic doesn't apply, and Step 5's 1.5× line-height rule would overwrite Via's approved 34/44, 18/26, and 16/26 pairs.

## Step 1 — Get the input

If the user hasn't already attached a file, ask them to paste **one** of:

- A PDF export of the full creative — **strongly preferred**, and **ask for both the desktop and the mobile export** if they exist. Two PDFs give you the exact responsive type scale.
- One image per module/section, **or**
- The whole creative as a single image (least accurate — no measurements).

`.fig` files cannot be opened directly. If the user only has a Figma link, ask them to export PDFs (desktop + mobile) or PNGs.

If `$1` is provided, treat it as the target project folder (where `ProjectMiddle01.htm` lives). Otherwise use the current working directory if it's under `E:\Lumenalta\AAA SFMC Files\<YEAR>\`; else ask.

## Step 2 — Measure the creative (do this before looking at any module)

### 2a. PDF: extract exact metrics

Figma exports email frames at their true pixel width (640 desktop / 320 mobile), so **PDF points map 1:1 to CSS px**. Run:

```
py .claude/scripts/parse_creative_pdf.py "<desktop.pdf>" --mobile "<mobile.pdf>"
```

Add `--pages 1-3` for multi-page exports, `--json` if you want to post-process. If it reports `pymupdf is required`, run `py -m pip install pymupdf` once.

The report gives you, per page:

- **BACKGROUND BANDS** — full-width fills top-to-bottom with the palette name (`white`, `sky-20`, `blue (navy)`, `cloud-20`, `lime-30`, `cerulean`, `slate`). This *is* the section list. Use it in Step 3.
- **ROUNDED CARDS** — inset panels with their width, y-range, and fill. A 580px-wide white card on a colored band is the single most important signal for variant choice.
- **SQUARE-CORNER INSET PANELS** — same, without radius.
- **IMAGES** — hero/inline image bboxes, so you get real `width`/`height` attributes.
- **TEXT** — every line with `size / line-height`, alignment, the background it sits on, and its color.
- **DESKTOP ↔ MOBILE TYPE SCALE** — each string paired across breakpoints, with the ready-to-paste `style="font-size:…; line-height:…"` plus the matching mobile `class="font-size-…"`. It flags sizes that have no utility class and cases where mobile is larger than desktop.

If the export width isn't 640 or 320 the script says so and prints the scale factor — apply it to every size before using it.

### 2b. Render high-zoom crops for what measurement can't tell you

Numbers don't give you font weight, icon artwork, or reliable copy. The Type3 fonts Figma embeds also corrupt extracted text (stray `(` at soft line breaks, mangled `ff`/`fi` ligatures, phantom `€`). So for each section, render a crop and read it:

```
py - <<'EOF'
import fitz
doc = fitz.open(r"<desktop.pdf>")
doc[0].get_pixmap(matrix=fitz.Matrix(3, 3), clip=fitz.Rect(20, <y0>, 620, <y1>)).save("hero.png")
EOF
```

Then `Read` the PNG. Use the y-ranges straight from the band/card list. From the crop, read:

- **Font weight** per run — and specifically **which words inside a line are bolder**. A bold lead-in (a personalized `[Name],` or a bolded phrase) belongs on `<strong style="font-weight:700">`, not on the whole element.
- **Icon artwork** — shape, whether it's a filled circle, and its pixel size.
- **Rule/divider lines** — where they are and whether they span the full card width.
- **Copy, verbatim** — always transcribe from the crop, never from the text extraction.

### 2c. Pull the real tracking URLs from the Jira ticket

Don't leave `href`s as placeholders when the intake already has them. The ticket Description carries a **Campaign URLs** table (URL Placement | Type of Clickable Asset | Cell Instructions | Final Web URL). Run the intake parser and read `campaign_urls`:

```
py .claude/scripts/parse_intake.py "<ticket.doc>"
```

Each row gives `placement`, `section` (from a `(section N)` prefix — this matches the section order in the creative, so it maps a URL straight to a module), `type` (`Image` / `CTA Button` / `Text Link`), `cell_instructions`, and `url`.

`cell_instructions` does double duty depending on `type`: on an **`Image`** row it is that image's **alt text** (see Step 7); on a `CTA Button` / `Text Link` row it is the visible label, which is what you match the element on.

Match rows to elements by `section` first, then by label: `cell_instructions` normally equals the button label or link text, so "DMV Services" → the `<a>` around "DMV Services". Then:

- **Never HTML-escape the URL.** Paste the URL **verbatim**, including all `utm_*` params, and keep every `&` as a literal `&` — an `&amp;` inside an `href` breaks the query string in SFMC's link wrapping and in some clients, so the tracking params stop joining. Never edit, shorten, "tidy", or entity-encode one.
- Per `CLAUDE.md`: no URLs inside AMPscript variable values, and no link aliases.
- A row of type `Image` means that image is wrapped in an `<a>` — restore the module's link wrapper if you dropped it.
- If an element in the creative has **no** matching row, leave the example `href` and list it in Step 8 as still-placeholder. If a row has no matching element, say so — it usually means a section was missed.
- Also read the ticket's **Comments** — reviewers frequently flag a wrong URL there (e.g. a DMV link pointing at the wrong state). Quote anything relevant in the report so the user can confirm the table is the corrected version.

If the ticket has no Campaign URLs table, `campaign_urls` is `[]` — carry on with placeholders.

### 2d. Transcribe copy per section, and flag every weight difference

Keep a per-section copy block keyed to the section number you'll propose in Step 4. Capture, in reading order: headings/eyebrows (noting relative emphasis), body paragraphs (including inline bold/italic), button labels, list items, and legal/disclaimer copy (flag it for `ProjectLegal.htm` — don't stuff it into a module). Note where images sit and their measured dimensions; their `alt` comes from the Campaign URLs table's `Cell Instructions` column, **never composed from the artwork** (see Step 7). Mark anything you can't read confidently `[ILLEGIBLE — confirm]` rather than guessing.

**Then run an explicit weight-and-copy pass.** Font weight is the single easiest thing to lose, because the measurement script can't see it and the example module's weight silently carries over. For **every** text element, write down the weight you read from the crop and compare it to what the module ships:

- Render the crop at **5×** (`fitz.Matrix(5, 5)`) over a tight region containing both the element and an adjacent element of known weight. Stem thickness is unmistakable at that zoom; at 2× it is not.
- Judge each run against its neighbours, not in isolation — "is this heavier than the body copy directly beneath it?" is answerable; "is this 600 or 700?" often isn't.
- When 600 vs 700 is genuinely ambiguous, **check what the source module specifies for that same element** and prefer it. V3 is internally consistent: 20px row headings are 600, 32px display headings are 700. Both fall back to Arial Bold anyway, so the difference only shows in Apple Mail / iOS Outlook / macOS OL 365.
- Watch for elements that are **links**, not bold text — an underline plus heavier weight usually means an `<a>`, and it needs an `href` from the Campaign URLs table (Step 2c), not a `<strong>`.

Produce a short list of every element where the creative's weight or copy differs from what the chosen module ships, and **ask the user to confirm before applying**. Do not silently adopt the module's weight, and do not silently "correct" the creative's copy. Include this list in the Step 6 proposal, e.g.:

```
Weight/copy deltas vs. module defaults:
  • Row headings (DMV Services, Insurance, …) — creative is heavier than body copy;
    #icons-left specifies 600. Module default here would leave them 400.  → confirm 600 vs 700
  • Date line "August 15, 2026 | 11AM-2PM" — creative 700; module ships 400.
  • Em dash in "vacation yet—save" — module copy uses a hyphen.
```

### 2e. Screenshots only (no PDF)

Say plainly in the proposal that sizes are estimated. Anchor estimates against something of known size in the same image — the 640px frame width, or the shared header's `INSURANCE` label (16px desktop / 12px mobile) — rather than guessing in the abstract.

## Step 3 — Build the background chain first

Write out the band list from the report, top to bottom, before opening any module file. This is the skeleton of `ProjectMiddle01.htm`: **one band = one top-level `<tr>`**, and its comment must name the color (`<!-- Content - sky-20 - 640px on desktop, 100% on mobile - Start -->`).

Rules that follow from the band list:

- **Contiguous same-color bands are ONE band.** The script already merges them. If the report shows a single `sky-20` band from y=645 to y=1625 covering two visual sections, those two sections are both on sky-20 — do not build the second one on white because it happens to contain a white card.
- **A rounded card inside a band is structural.** Reproduce the band color *and* the card (`background-color:#ffffff` + `border-*-radius:15px` on the inner 580px table). Never flatten a band-plus-card into a plain white section — the card's edges disappear and the section reads as a different design.
- **Ignore the top navy band and the big navy band at the bottom** — those are `SharedTop03_*` (header) and `SharedBtm01_*`/`SharedBtm02_*` (footers), not your content.
- **Copy the module's own gradient convention — don't extrapolate.** The Gmail iOS dark-mode rule (`background-color` paired with `background-image:linear-gradient(<c>,<c>)`) is applied in `Modules_V3_Styles.html` to the colors that actually get inverted: navy `#003087`, black, slate, and the `#5b6670` table caption. It is *not* applied to `sky-20` `#ccecf9` or to the white card. Match what the source snippet does; adding a gradient where the boilerplate doesn't use one is a silent deviation.
- White copy on a dark background still needs the `gmail-blend-screen` / `gmail-blend-difference` wrappers.

Then sanity-check the vertical rhythm: band top → card top is the section's top padding, card bottom → band bottom is its bottom padding. The modules use `padding: 30px 0` desktop / `padding-top-20 padding-btm-20` mobile.

### 30px between modules — never 60px

**The gap between any two adjacent modules must be exactly 30px on desktop (20px on mobile).** Each example module ships padding on *both* its top and its bottom, because each one is presented standalone in `Modules_V3_Styles.html`. Stack two of them verbatim and the paddings add: 30 + 30 = **60px**, which is double the spacing standard and visibly wrong against the creative. Measure the creative and you will see ~30px card-bottom → next-card-top; that is the number to hit.

Collapse it when you stitch (Step 7), not by editing the creative's measurements. The rule:

- **Every module keeps its 30px top padding** (`padding-top-20` on mobile).
- **Every module except the last one has its bottom padding zeroed** — `padding:30px 0 0 0`, and drop the `padding-btm-20` mobile class from that same `<td>`.
- **The last module keeps its 30px bottom padding**, so the final card clears the blue footer.

That yields 30px above the first card, 30px between every pair, and 30px below the last — top and bottom of the content area included.

Watch for modules that split their padding across **two** `<tr>`s (`#icons-left-skinny` is the common one: a top `<td style="padding: 30px 0 0 0" class="padding-top-20">` for the heading half of the card and a separate bottom `<td style="padding:0 0 30px 0" class="padding-btm-20">` for the bullets half). The bottom padding lives on the second `<tr>` — that is the one to zero, not the first.

If the creative genuinely shows something other than 30px between two sections, say so and use the measured value; but 60px is never the answer, and it is always a stitching artifact rather than a design decision.

## Step 4 — Map sections to modules, and pick the variant deliberately

**Always read `Modules_V3_Styles.html` FIRST.** It is the most up-to-date reference and the source of truth for module styling. Only fall back to the other `BoilerplateV2_ExampleModules/*` files for sections it does not cover.

### The "Skinny" rule

This one distinction explains most variant families in `Modules_V3_Styles.html`:

| | Non-skinny | **Skinny** |
|---|---|---|
| Band | full-width `white` | colored (`sky-20`, `cerulean`, `lime-30`, …) |
| Inner card | none — content sits directly on the band | 580px card, `background-color:#ffffff`, `border-radius:15px` |
| Corner radius in use | `30px` (buttons / images only) | `15px` (the card) |

So: **colored band + white rounded card ⇒ you want the `…-skinny` variant.** White band edge-to-edge ⇒ the non-skinny one.

### Variant matrix for `Modules_V3_Styles.html`

Anchors are the `id="…"` values on each section's heading. Confirm against the file — this table is a shortcut, not a substitute for reading the snippet.

| Anchor | Band | Card | Heading (desktop / mobile class) |
|---|---|---|---|
| `img-cta-top` / `img-cta-bot` | white | — | — |
| `img-cta-skinny-top` / `img-cta-skinny-bot` | sky-20 | white, r15 | — |
| `img-cta-skinny-alert` | sky-20 | white, r15 | — |
| `deals-floating` | cerulean | white + `#efeeee`, r15 | 20px center / `font-size-16` |
| `2col-img-l-skinny` | sky-20 | — (r30 images) | — |
| `2col-img-l-skinny-grey` | white | — | 24px left |
| `2col-img-r-skinny-grey` | white | `#f3f3f4`, r15 | 28px left / `font-size-20` |
| `2col-img-r-skinny-blue` | sky-20 | navy panel | 24px left, white copy |
| `icons-left` | **white** | **none** | 28px **center** |
| `icons-left-skinny` | **sky-20** | **white, r15** | 32px **left** / `font-size-28` |
| `icons-left-blue-skinny` | sky-20 | navy panel | 32px left, white copy / `font-size-28` |
| `icons-center-skinny` | sky-20 | white, r15 | 32px center / `font-size-28` |
| `icons-3col` | white | — (r30) | 24px center / `font-size-24` |
| `sms-module` | orange + lime-30 | — | — |
| `sms-module-skinny` | sky-20 | r15 | — |
| `wavy-cta` / `wavy-cta-3col` | lime-30 | — (r30) | 24px center |
| `2x2-images` | white | — | 24px center |
| `table` | white | r30 | 28px center + 16px panel heading / `font-size-14` |
| `table-bg-color-variation` | white | r15 | white panel heading |
| `discounts-no-promo` / `-promo` / `-xsell` | white | r15 | 24px center / `font-size-16` |

The four `icons-*` rows are the classic trap: they render very differently but their inner bullet markup is nearly identical, so a diff of the snippet alone won't tell you which one you want. Choose on **band + card + heading alignment**, in that order.

### Other example files

For sections `Modules_V3_Styles.html` doesn't cover:

| Section pattern | Module |
|---|---|
| 1-col copy + button | `Modules_AltTxtWhite_1ColDesktop.html` / `Modules_AltTxtBlueAsphalt_1ColDesktop.html` |
| 2-col image + copy | `Modules_AltTxtWhite_2ColDesktop.html` / `_AltTxtBlueAsphalt_` |
| Headline as an image | `Modules_HeadingOnImgTag_AltTxtWhite.htm` / `_AltTxtBlueAsphalt.htm` |
| UL bullets | `Assets_ULlists.html` / `Assets_ULlists_alternative.html` |
| OL list | `Assets_OLlists.html` |
| Custom image bullets | `Modules_AccessibleImgBullets_AltTxtWhite.html` / `_AltTxtBlueAsphalt` |
| Letter / narrative copy | `Modules_LetterStyleExample.html` |
| Urgent / alert banner | `Modules_UrgentNoticeExample.html` |
| Auto repair specific | `Modules_AutoRepair_AltTxtBlueAsphalt.html` |
| Tabular data | `Modules_AccessibleTablesForTabularData.html` |
| Data-driven content | `Modules_DataDrivenExamples.html` |
| Buttons (snippet) | `Assets_Buttons.html` |

`AltTxtWhite` = alt text renders white (dark backgrounds); `AltTxtBlueAsphalt` = dark blue/black alt text (light backgrounds).

### When a section matches no module — ask, don't guess

Every band and card in the Step 3 chain must be accounted for by a module. If a section has no reasonable match, **do not skip it and do not force the nearest module onto it.** Say what you see, then ask the user which way to build it, offering:

1. **Build it by hand** in HTML/CSS following the BoilerplateV2 conventions — table-based nesting, all five required `<table>` attributes, width in `style`, `w-100`/`w-90` on the inner table, the measured type scale, `linear-gradient` pairs where the palette calls for them, and MSO conditionals where relevant. Name the closest reference module so the user knows what it will resemble.
2. **Drop in a placeholder image** at the measured dimensions with correct markup — often the right answer, because the designer may have intended a flattened graphic all along. The tell: the section renders as an image block in the report with **no live text lines over it**, meaning the words are baked into the artwork. Use an `https://fpoimg.com/<W>x<H>?text=…` URL so it can't be mistaken for a finished asset, take `alt` from the Campaign URLs row's `Cell Instructions` if there is one and otherwise leave `alt=""` (Step 7), and only wrap it in `<a>` if that table has a row for it.
3. **Something else** — a new shared module, a copy change, or a question back to the designer.

Also treat a **hybrid** as a thing you must declare: taking one module's wrapper and another's inner rows is often correct (e.g. `#icons-left-skinny`'s sky-20 band and white card, with `#icons-left`'s 20px-heading + 14px-description rows), but say plainly that neither module fits alone rather than presenting it as a clean match.

## Step 5 — Retype the type scale to the creative

The example modules' font sizes are **placeholders**. Apply the measured scale from Step 2a to every heading, paragraph, button label, table caption, and cell. Then check each against the constraints below.

### Desktop size inline, mobile size as a class

```html
<h2 class="blue font-size-28" style="mso-line-height-rule:exactly; margin:0; text-align:center;
    font-size:32px; color:#003087; font-family:'SmartV1',Arial,Helvetica,sans-serif;
    font-weight:600; line-height:48px;">
```

The inline `font-size` / `line-height` is the **desktop** value. The `font-size-*` class only applies under `max-width:599px`, so it carries the **mobile** value. If both breakpoints share a size, use no class.

Utility classes live in **two** GlobalModules files — check both before concluding a class doesn't exist:

- `399733_SharedTop01_021825.htm` — the required base set: `w-*`, `img-w-*`, `mobile-hidden`, `mobile`, `margin-*`, `padding-*`, `text-align-*`, `bg-*`.
- `399733_SharedCSS_102425.htm` — the optional set, including every `font-size-*`: **12, 14, 16, 20, 22, 24, 28, 32, 47, 48, 52, 57, 64, 72, 74** (plus `-only` variants that set size without line-height, and `52-special` / `80-special`), and the matching `sup-for-*` / `sub-for-*`.

If the creative's mobile size isn't on that list, either round to the nearest one or add the class to `ProjectCSS.htm` — and say which you did. The script flags this for you.

Matching `sup-for-font-size-*` / `sub-for-font-size-*` classes exist for 12–32; use the one matching the *mobile* size, with the desktop `font-size` / `vertical-align` inline.

### Web font constraints (`BoilerplateV2_ExampleModules/Assets_WebFonts.html`)

- Only these weights resolve to a Smart woff2: **300, 400, 600, 700, 900** (each with an italic). Anything else silently falls back.
- Weights **< 600 fall back to Arial Regular**; **≥ 600 fall back to Arial Bold**.
- **Never mix 600–900 in a single element**, and **never mix 100–500 in a single element** — in the Arial fallback they collapse to the same weight and the hierarchy is lost. Mixing e.g. 400 with 700 *is* fine, because they land on Regular vs Bold.
- Mixed weight inside one line goes on `<strong>` / `<em>` / `<a>` (semantics survive), never a bare `<span>`.
- Web fonts only render in iOS/MacOS Apple Mail, iOS Outlook, and MacOS OL Office 365. Everywhere else shows Arial — so never rely on a weight difference alone to carry meaning.
- Heading elements need `mso-line-height-rule:exactly;`. Body copy does not.
- Only `@font-face` the weights the email actually uses — the header CSS must stay under 15 kB and total code under 102 kB.

### Line-height is always 1.5 × font-size

Non-negotiable for body and heading copy: **12/18, 14/21, 16/24, 20/30, 22/33, 24/36, 28/42, 32/48, 36/54, 44/66.** Compute it from the font size — do not carry over the line-height that happened to be on the example module, and do not round a measured value to something that breaks the ratio.

This applies to the inline desktop value *and* the mobile class. Every `font-size-*` utility already ships its own 1.5× line-height, so a class plus a conflicting inline `line-height` is a bug: `class="font-size-14"` with inline `line-height:24px` renders 14px/21px on mobile and 16px/24px on desktop only if the inline `font-size` is 16px. Check both breakpoints resolve to a 1.5× pair.

Two exceptions only:

- `<sup>` / `<sub>` carry `line-height:0` (with `vertical-align` doing the work).
- The large display classes `font-size-57` (1.33×), `font-size-64` (1.0×), `font-size-52-special` (1.19×), `font-size-80-special` (1.12×) are intentionally tight. Use them as-is for display type; never imitate their ratio at body/heading sizes.

If the creative measures a non-1.5× line-height at a body/heading size, the creative is wrong — use 1.5× and say so in the report.

## Step 6 — Propose the sequence

Output a numbered plan. Each row must state the module **and the evidence for the variant**, then the copy and the type scale:

```
2. Modules_V3_Styles.html #icons-left-skinny — "Get Life Insurance Through AAA" + 3 checkmark rows
   Why this variant: band y=1216-1625 is sky-20, with a 580px white rounded card at
     y=1246-1595 → skinny. (#icons-left is white-band/no-card — wrong.)
   • Heading: "Get Life Insurance Through AAA"  — 24px/36 center, mobile 28px (font-size-28)
     ! mobile > desktop, unusual — confirm
   • Row 1: "Get life insurance for as low as $1 a day; that's around $30 a month." (2) — 14px/21
   • Row 2: "Affordable rates designed to meet your specific coverage needs." — 14px/21
   • Row 3: "Members save 10% on term life insurance from AAA." — 14px/21
   • Icons: 50x50 navy filled circle, white check — module ships 70x70, resize
   • Image src: FPO https://fpoimg.com/580x420?text=580x420 — needs real asset
   • Spacing: bottom padding zeroed (not the last module) → 30px to section 3
```

Then `AskUserQuestion`: **approve as-is**, **edit the sequence / copy**, or **swap a row**. Do not start writing until the user approves.

## Step 7 — Stitch, then apply the spec

For each approved row, insert the module: extract the snippet between the `<!-- … - Start -->` / `<!-- … - End -->` comments, validate against the table-markup rules in `CLAUDE.md`, and append to `ProjectMiddle01.htm` in order, wrapped in its own `<!-- <module-friendly-name> - Start -->` / `- End -->` pair.

Then apply the approved spec slot-by-slot:

- **Copy** — replace the text content only. Leave the surrounding `<td>` / `<span>` / `<p>` markup, classes, and inline styles alone except for the size changes below. If the creative has more or fewer paragraphs than the module, add/remove sibling rows following the pattern already in the snippet — don't restructure the table.
- **Font sizes** — retype `font-size` / `line-height` inline and fix the `font-size-*` class to the mobile value. This is the step that gets skipped; it is not optional.
- **Font weights** — set from the crop, within the weight rules above. A bolded run inside an otherwise-regular line becomes `<strong style="font-weight:700">` (or a `<span>` when the emphasis is purely visual, as with a personalized name).
- **First-name personalization** — if a section's copy contains a personalized name, **the entire sentence belongs in the `@FirstNameIntro*` variable in `ProjectAmpscript.amp`**, and `ProjectMiddle01.htm` contains nothing but `%%=v(@FirstNameIntro)=%%` inside the element. Do not append the rest of the sentence after the variable in the body — a dangling `…=%%id you know…` fragment is the symptom of getting this backwards. To bold only the name, put the span *inside* the AMPscript value:

  ```
  IF LENGTH(@FirstName) < 2 OR LENGTH(@FirstName) > 15 OR EMPTY(@FirstName) OR TRIM(@FirstName) == '' THEN
      SET @FirstNameIntro = 'Did you know AAA has exclusive Member&nbsp;savings?'
  ELSE
      SET @FirstNameIntro = CONCAT('<span style="font-weight:700">',@FirstName,',</span> did you know AAA has exclusive Member&nbsp;savings?')
  ENDIF
  ```

  `@FirstNameIntro3` already embeds a `<br>` this way, so inline HTML in the value is the established idiom. Write each branch as a complete, correctly-capitalized sentence — never splice a leading letter (`'D'` / `', d'`) across the two files. Entities and `&nbsp;` widow control are fine in the value; URLs are not (see `CLAUDE.md`). Leave the surrounding `IF` conditional itself untouched.
- **Alignment** — `text-align` per the report. `icons-left-skinny` ships a left-aligned heading; if the creative centers it, change `text-align` (and drop the `text-align-center` mobile class if it now conflicts).
- **Background colors** — the band color and card fill from Step 3, each with its `linear-gradient` pair.
- **Icon / image dimensions** — set `width` / `height` from the IMAGES section and the crops. If you change an icon's size, check whether the module's `img-w-*` mobile class still makes sense; a fixed-size icon that doesn't scale should just carry `width`/`height` and no class.
- **Button labels** — visible label only; keep the MSO letter-spacing hack (`<!--[if mso]><em style="letter-spacing:25px; …">&nbsp;</em><![endif]-->`) on both sides intact.
- **Alt text comes from the Campaign URLs table's `Cell Instructions` column — never author it.** For each `<img>`, find its row in `campaign_urls` (Step 2c) and use that row's `cell_instructions` verbatim as the `alt`. That column is the client's description of the asset and is the agreed source of alt text.

  ```
  placement "Hero Image" | type "Image" | cell_instructions "Community Event"
      -> <img src="…" alt="Community Event" …>
  ```

  An image with **no** matching row gets `alt=""` — that covers decorative icons, spectrum bars, spacers, and any lockup the table doesn't list. Never invent a string, and never transcribe the words you can see in the artwork: that is still authoring copy for a slot nobody filled. If an image has no row but you think it needs alt text, **say so and ask** — don't add it and mention it afterwards. Anything left `alt=""` goes in the Step 8 report so the wording can be collected in one pass.

  `cell_instructions` on `CTA Button` / `Text Link` rows is the visible label, not alt text — those elements have no `alt`. Use those rows only to match the link to its `href`.

  Watch the ticket Comments too: reviewers often ask the requestor to add hero alt text. A comment requesting alt text is not the alt text — flag it as an open item.
- **Widow control** — where the original used a trailing `&nbsp;` to prevent a one-word last line, do the same before the final word of the replacement copy. Nowhere else.
- **Inter-module padding** — apply the 30px rule from Step 3: zero the bottom padding on every module except the last, and drop that `<td>`'s `padding-btm-20` mobile class. Do this as you append each module, then re-check the whole file top-to-bottom — a module inserted later can silently turn the previous last module back into a middle one.

- **Link `href`** — apply the real tracking URLs from Step 2c verbatim, with literal `&` between params (never `&amp;`). Only leave an example `href` where the Campaign URLs table has no matching row.

### Every image `src` is an FPO placeholder

**Replace every `src` in the stitched modules with an FPO placeholder carrying that image's dimensions** — never leave an `https://image.emails.goaaa.com/...` example asset URL in a real project. Those example URLs render as somebody else's finished artwork, which reads as a completed build in review and hides the fact that the asset team hasn't delivered yet. An FPO cannot be mistaken for the real thing.

Format — the dimensions appear in both the path and the `text` label, so the placeholder is self-documenting on screen:

```
https://fpoimg.com/<W>x<H>?text=<W>x<H>
```

```html
<img src="https://fpoimg.com/580x580?text=580x580" alt="Buy One Get One" width="580" height="580" …>
```

- `<W>x<H>` are the **measured** dimensions from Step 2a's IMAGES section (or the module's fixed dimensions where the creative confirms them). They must match the `width` / `height` attributes on the same tag.
- This applies to **every** `<img>`: heroes, inline photos, icon bullets, spectrum bars, 2-up cards — all of them.
- **Mobile-only rows keep `width="0" height="0"` on the tag**, but the FPO URL still carries the *mobile crop's* real dimensions, because that is what the asset team has to produce. If you only measured a desktop export you don't know the mobile crop size — use the desktop dimensions, and say in the Step 8 report that the mobile crop dimensions are unconfirmed pending the mobile Figma frame.
- `alt` is unaffected — it still comes from the Campaign URLs table (or stays `alt=""`), never from the FPO text.
- Leave the surrounding `<a>` wrapper, `class`, `style`, radius, and `img-w-*` classes exactly as the module ships them.

Then list every FPO in the Step 8 report, grouped by module with its dimensions, so the asset request can be raised in one pass.

Copy hygiene: convert straight quotes to curly (`'` `'` `"` `"`), use entities (`&nbsp;`, `&trade;`, `&reg;`, `&#8209;` for non-breaking hyphens) where the module already does — **in visible copy only, never inside an attribute value like `href` or `src`**. Body copy may contain entities and normal punctuation (unlike `@SubjectLine`/`@PreviewText`). Never invent copy the creative doesn't show — flag empty slots instead of filling them.

## Step 8 — Report

Print:

- Number of modules stitched, and the final `ProjectMiddle01.htm` outline top-to-bottom.
- **Background chain** — the band list you built and which variant each maps to, so a wrong variant is obvious at a glance.
- **Type scale applied** — a small table of element → desktop size / mobile class, and any size you rounded or any class you had to add to `ProjectCSS.htm`. Confirm every pair is 1.5× at both breakpoints.
- **Personalization** — any `@FirstNameIntro*` value you wrote into `ProjectAmpscript.amp`, showing how both the fallback and personalized branches read as full sentences.
- **Weight/copy deltas applied** — the list from Step 2d and what the user confirmed for each.
- **URLs wired** — each element → its `utm_content` value, so a mismatch is easy to spot; plus any Campaign URLs row with no matching element, or element with no row. Grep the file for `amp;` first: any hit inside an `href` is an escaping bug — fix it before reporting.
- **Inter-module spacing** — confirm the gap between every pair of adjacent modules is 30px desktop / 20px mobile, and name the module whose bottom padding you kept (it should be the last one, and only the last one).
- **Sections built by hand or as placeholder images** — what you chose and why, for anything with no module match.
- **Copy filled in** — plus any slot left as placeholder because the creative didn't cover it.
- **FPO images** — every `<img>` grouped by module with its `<W>x<H>`, so the asset request goes out in one pass. Flag any mobile-crop dimension you carried over from the desktop export because no mobile frame was supplied. Plus any `href` with no Campaign URLs row.
- **Alt text** — each image's `alt` and the Campaign URLs row it came from, plus every image left at `alt=""` because it had no row, so the user can collect any missing wording in one pass. Call out any ticket Comment that asked for alt text.
- Any `[ILLEGIBLE — confirm]` copy, and any measurement the script flagged (undefined mobile class, mobile > desktop).
- Legal/disclaimer copy that belongs in `ProjectLegal.htm`.
- Reminder that the data extension `.xls` may need tab cleanup (`/edit-data-extension`).

## Honesty about limits

This is a **suggestion** step, not magic. Some creatives need combinations that don't exist in the example files, or custom rows with no direct match — say "I'd build this section by hand — closest reference is X" rather than forcing a bad match.

Measurement caveats worth stating out loud:

- Extracted text is unreliable (Type3 glyph artifacts) — copy comes from the crops.
- Font weight, color intent, and icon artwork are read visually and can be wrong; the script's `color` column is inferred from glyph fills and can miss on anti-aliased or gradient text.
- Multi-column blocks can flatten oddly in a PDF export, so a 2-col layout may read as 1-col. The `x0` values in the TEXT section are the tell: two distinct `x0` clusters at the same `y` means two columns. If in doubt, ask the user to confirm column counts before stitching.
- The script reports what the *creative* does. Where that conflicts with a hard constraint in `CLAUDE.md` (CSS budget, no straight quotes in subject line, required MSO hacks), the constraint wins — flag the conflict rather than reproducing the creative exactly.
