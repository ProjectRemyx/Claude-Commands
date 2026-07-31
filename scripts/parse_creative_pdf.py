"""Extract exact type + background metrics from a Figma PDF export of an email creative.

Used by /generate-projectmiddle01 so module selection and font sizes come from
measured values instead of eyeballing a rasterized page.

Figma exports email frames at their true pixel width (640 for desktop, 320 for
mobile), and PDF points map 1:1 to CSS px at that width. Everything reported
here is therefore already in CSS px.

Usage
-----
    py .claude/scripts/parse_creative_pdf.py DESKTOP.pdf
    py .claude/scripts/parse_creative_pdf.py DESKTOP.pdf --mobile MOBILE.pdf
    py .claude/scripts/parse_creative_pdf.py DESKTOP.pdf --mobile MOBILE.pdf --json

Requires: pymupdf  (py -m pip install pymupdf)
"""

import argparse
import json
import os
import re
import sys

try:
    import fitz  # pymupdf
except ImportError:
    sys.exit("pymupdf is required:  py -m pip install pymupdf")

# ---------------------------------------------------------------------------
# AAA MWG palette. Keys are the names used in the "Content - <name>" module
# comments in BoilerplateV2_ExampleModules/, so a reported band name can be
# matched straight against a module variant.
# ---------------------------------------------------------------------------
PALETTE = {
    "#ffffff": "white",
    "#003087": "blue (navy)",
    "#ccecf9": "sky-20",
    "#f3f3f4": "cloud-20",
    "#efeeee": "cloud (efeeee)",
    "#e1e1e2": "cloud (e1e1e2)",
    "#d9e9b3": "lime-30",
    "#00a0df": "cerulean",
    "#323e48": "slate",
    "#5b6670": "slate-70 (table caption)",
    "#d1d3d4": "grey rule / table row",
    "#c1c4c7": "grey table row",
    "#d1d2d4": "hairline rule",
    "#000000": "black",
    "#ff6a13": "orange",
}

# Where the responsive utility classes live: SharedTop01 holds the required
# base set (w-*, mobile-hidden, img-w-*), SharedCSS the optional font-size-*
# set. A size missing from both needs a class added to ProjectCSS.htm.
_HERE = os.path.dirname(os.path.abspath(__file__))
SHARED_CSS = [
    os.path.join(_HERE, "..", "..", "GlobalModules", "399733_SharedCSS_102425.htm"),
    os.path.join(_HERE, "..", "..", "GlobalModules", "399733_SharedTop01_021825.htm"),
]

# Web font weights that actually resolve to a Smart woff2 (Assets_WebFonts.html).
WEB_FONT_WEIGHTS = (300, 400, 600, 700, 900)


def hexc(c):
    if c is None:
        return None
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in c)


def name_color(h):
    return PALETTE.get(h, "unmapped")


def load_font_size_classes():
    """Return {size_px: class_name} for the .font-size-* classes that exist."""
    out = {}
    for path in SHARED_CSS:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                css = fh.read()
        except OSError:
            continue
        for name, size in re.findall(
            r"\.(font-size-[0-9a-z-]+)\s*\{\s*font-size:\s*(\d+)px", css
        ):
            if name.endswith("-only") or name.endswith("-special"):
                continue
            out.setdefault(int(size), name)
    return out


def n_curves(drawing):
    return sum(1 for item in drawing["items"] if item[0] == "c")


def is_rect(drawing):
    """Plain rectangle fill. Figma emits these as either 're' or 4 'l' edges."""
    return n_curves(drawing) == 0


def is_rounded_rect(drawing):
    """Rounded rect: 4 corner curves, or 2 when only one end is rounded (the
    top/bottom halves of a split panel, as in the rate-table modules)."""
    return 2 <= n_curves(drawing) <= 8


def is_glyph_run(drawing):
    """Type3 glyphs come through as drawings with many small curves."""
    return n_curves(drawing) > 20


def covered_fraction(inner, outer):
    """How much of `inner` sits inside `outer`."""
    inter = inner & outer
    if inter.is_empty or inner.is_empty:
        return 0.0
    return abs(inter) / abs(inner)


def analyze_page(page, page_no):
    pw, ph = page.rect.width, page.rect.height
    drawings = page.get_drawings()

    bands, cards, panels, rules, glyph_runs = [], [], [], [], []
    for d in drawings:
        r = d["rect"]
        fill = hexc(d.get("fill"))
        if fill is None:
            continue
        if is_glyph_run(d):
            glyph_runs.append((r, fill))
            continue
        if r.width < 8 or r.height < 1:
            continue
        if r.height <= 3 and r.width >= 40:
            rules.append({"y": round(r.y0, 1), "x0": round(r.x0, 1),
                          "x1": round(r.x1, 1), "color": fill})
            continue
        if is_rect(d) and r.width >= 0.98 * pw and r.height >= 8:
            bands.append({"y0": round(r.y0, 1), "y1": round(r.y1, 1),
                          "color": fill, "name": name_color(fill)})
        elif is_rect(d) and r.width >= 300 and r.height >= 24:
            panels.append({"y0": round(r.y0, 1), "y1": round(r.y1, 1),
                           "x0": round(r.x0, 1), "x1": round(r.x1, 1),
                           "w": round(r.width, 1), "color": fill,
                           "name": name_color(fill)})
        elif is_rounded_rect(d) and r.width >= 120 and r.height >= 20:
            cards.append({"y0": round(r.y0, 1), "y1": round(r.y1, 1),
                          "x0": round(r.x0, 1), "x1": round(r.x1, 1),
                          "w": round(r.width, 1), "h": round(r.height, 1),
                          "color": fill, "name": name_color(fill),
                          "curves": n_curves(d)})

    # Merge adjacent same-color bands; Figma slices one background into pieces.
    bands.sort(key=lambda b: b["y0"])
    merged = []
    for b in bands:
        if merged and merged[-1]["color"] == b["color"] and b["y0"] - merged[-1]["y1"] <= 1.5:
            merged[-1]["y1"] = max(merged[-1]["y1"], b["y1"])
        else:
            merged.append(dict(b))
    # Drop the page-sized backdrop.
    merged = [b for b in merged if not (b["y0"] <= 1 and b["y1"] >= ph - 1)]

    # Figma stacks an opaque black drop-shadow rect at the same origin as each
    # card. Drop a black card whenever a coloured one starts in the same place.
    cards.sort(key=lambda c: (c["y0"], c["x0"]))
    cards = [
        c for c in cards
        if c["color"] != "#000000"
        or not any(o is not c and o["color"] != "#000000"
                   and abs(o["x0"] - c["x0"]) < 2 and abs(o["y0"] - c["y0"]) < 2
                   for o in cards)
    ]
    # Drop exact duplicates.
    uniq = []
    for c in cards:
        if any(abs(u["x0"] - c["x0"]) < 1.5 and abs(u["y0"] - c["y0"]) < 1.5
               and abs(u["y1"] - c["y1"]) < 1.5 for u in uniq):
            continue
        uniq.append(c)
    # A panel split into a top-rounded half and a bottom-rounded half (the rate
    # table modules) is really one panel, so rejoin those. Only pieces rounded
    # at ONE end qualify - exactly 2 corner curves each. Two fully-rounded
    # 4-curve cards separated by a gap are independent cards, however small the
    # gap, and fusing them would hide a whole section boundary.
    cards = []
    for c in uniq:
        prev = next((p for p in cards
                     if p["color"] == c["color"] and abs(p["x0"] - c["x0"]) < 2
                     and abs(p["x1"] - c["x1"]) < 2 and 0 <= c["y0"] - p["y1"] <= 400
                     and p.get("curves") == 2 and c.get("curves") == 2), None)
        if prev:
            prev["y1"] = max(prev["y1"], c["y1"])
            prev["h"] = round(prev["y1"] - prev["y0"], 1)
            prev["split"] = True
        else:
            cards.append(c)

    images = [
        {"y0": round(b["bbox"][1], 1), "y1": round(b["bbox"][3], 1),
         "w": round(b["bbox"][2] - b["bbox"][0], 1),
         "h": round(b["bbox"][3] - b["bbox"][1], 1)}
        for b in page.get_text("dict")["blocks"] if b["type"] != 0
    ]

    # ---- text lines -------------------------------------------------------
    lines = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            spans = [s for s in l["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            # Figma's Type3 export emits a stray '(' where a soft line break was.
            if text.endswith("(") and not text.endswith("((") and "(" not in text[:-1]:
                text = text[:-1].rstrip()
            rect = fitz.Rect(l["bbox"])
            size = round(max(s["size"] for s in spans), 1)
            color, best = None, 0.0
            for r, fill in glyph_runs:
                # A glyph run may span a whole paragraph, so ask how much of the
                # LINE the run covers - not how much of the run the line covers.
                cov = covered_fraction(rect + (-1, -1, 1, 1), r)
                if cov > best and cov > 0.5:
                    best, color = cov, fill
            lines.append({"y": round(rect.y0, 1), "x0": round(rect.x0, 1),
                          "x1": round(rect.x1, 1), "size": size,
                          "color": color, "text": text})
    lines.sort(key=lambda t: (t["y"], t["x0"]))

    # line-height = pitch between consecutive same-size lines in one paragraph
    for i, t in enumerate(lines):
        t["line_height"] = None
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            gap = round(nxt["y"] - t["y"], 1)
            if nxt["size"] == t["size"] and 0 < gap <= t["size"] * 2.2:
                t["line_height"] = gap
        if t["line_height"] is None and i > 0:
            prv = lines[i - 1]
            gap = round(t["y"] - prv["y"], 1)
            if prv["size"] == t["size"] and 0 < gap <= t["size"] * 2.2:
                t["line_height"] = gap

    # Alignment. A single line's insets are ambiguous, but a multi-line
    # paragraph is decisive: shared left edge => left, shared centre => centre.
    for t in lines:
        left, right = 0.0, pw
        for c in cards:
            if c["y0"] - 4 <= t["y"] <= c["y1"] + 4 and c["x0"] - 4 <= t["x0"] <= c["x1"] + 4:
                left, right = c["x0"], c["x1"]
                break
        t["container"] = [round(left, 1), round(right, 1)]

    paras, cur = [], []
    for t in lines:
        if cur and t["size"] == cur[-1]["size"] and 0 < t["y"] - cur[-1]["y"] <= t["size"] * 2.2 \
                and t["container"] == cur[-1]["container"]:
            cur.append(t)
        else:
            if cur:
                paras.append(cur)
            cur = [t]
    if cur:
        paras.append(cur)

    for para in paras:
        if len(para) > 1:
            x0s = [t["x0"] for t in para]
            mids = [(t["x0"] + t["x1"]) / 2 for t in para]
            if max(x0s) - min(x0s) <= 1.5:
                align = "left"
            elif max(mids) - min(mids) <= 2.5:
                align = "center"
            else:
                align = "left"
        else:
            t = para[0]
            left, right = t["container"]
            l_in, r_in = t["x0"] - left, right - t["x1"]
            if abs(l_in - r_in) <= 10 and l_in > 8:
                align = "center"
            elif r_in < l_in and l_in > 0.35 * (right - left):
                align = "right"
            else:
                align = "left"
        for t in para:
            t["align"] = align

    # which band/card is each line sitting on -> the bg color behind the copy
    for t in lines:
        bg = None
        for c in cards + panels:
            if c["y0"] - 4 <= t["y"] <= c["y1"] + 4 and c["x0"] <= t["x0"] <= c["x1"]:
                bg = c["name"]
        if bg is None:
            for b in merged:
                if b["y0"] <= t["y"] <= b["y1"]:
                    bg = b["name"]
        t["on"] = bg or "white"

    return {"page": page_no, "width": pw, "height": round(ph, 1),
            "bands": merged, "cards": cards, "panels": panels, "rules": rules,
            "images": images, "lines": lines}


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())[:44]


def pair_sizes(desktop_pages, mobile_pages, fs_classes):
    """Match copy across the two exports so each line gets desktop + mobile px."""
    mob = {}
    for p in mobile_pages:
        for t in p["lines"]:
            mob.setdefault(norm(t["text"]), t)

    pairs = []
    for p in desktop_pages:
        for t in p["lines"]:
            key = norm(t["text"])
            m = mob.get(key)
            if m is None:
                # Mobile rewraps the copy, so fall back to the longest shared
                # prefix. Require a decent run - a short prefix like "getlife"
                # would happily match an unrelated heading.
                best_len = 0
                for mk, mv in mob.items():
                    n = 0
                    while n < min(len(mk), len(key)) and mk[n] == key[n]:
                        n += 1
                    if n >= 12 and n > best_len:
                        best_len, m = n, mv
            entry = {"text": t["text"], "on": t["on"], "align": t["align"],
                     "color": t["color"],
                     "desktop": {"size": t["size"], "line_height": t["line_height"]},
                     "mobile": None, "notes": []}
            if m:
                entry["mobile"] = {"size": m["size"], "line_height": m["line_height"]}
                if m["size"] == t["size"]:
                    entry["css"] = (
                        f'font-size:{t["size"]:g}px; '
                        f'line-height:{t["line_height"] or round(t["size"] * 1.5, 1):g}px;'
                    )
                    entry["notes"].append("same size both breakpoints - no mobile class")
                else:
                    cls = fs_classes.get(int(m["size"]))
                    entry["css"] = (
                        f'font-size:{t["size"]:g}px; '
                        f'line-height:{t["line_height"] or round(t["size"] * 1.5, 1):g}px;'
                    )
                    entry["mobile_class"] = cls or f"font-size-{int(m['size'])} (NOT DEFINED)"
                    if not cls:
                        entry["notes"].append(
                            f'no .font-size-{int(m["size"])} utility class exists - '
                            f"add it to ProjectCSS.htm or round to a defined size"
                        )
                    if m["size"] > t["size"]:
                        entry["notes"].append(
                            "mobile larger than desktop - unusual, confirm with designer"
                        )
            else:
                entry["css"] = (
                    f'font-size:{t["size"]:g}px; '
                    f'line-height:{t["line_height"] or round(t["size"] * 1.5, 1):g}px;'
                )
                entry["notes"].append("no mobile match found")
            pairs.append(entry)
    return pairs


def print_report(desktop_pages, mobile_pages, pairs):
    for p in desktop_pages:
        print(f"\n{'=' * 78}\nPAGE {p['page']}  {p['width']:g} x {p['height']:g} px", end="")
        if abs(p["width"] - 640) < 1:
            print("   (640px desktop export - pt == CSS px)")
        elif abs(p["width"] - 320) < 1:
            print("   (320px mobile export - pt == CSS px)")
        else:
            print(f"   WARNING: not a 640/320 export - scale all sizes by {640 / p['width']:.4f}")

        print("\n-- BACKGROUND BANDS (full-width) -- pick the module variant that matches")
        for b in p["bands"]:
            print(f"   y {b['y0']:>7.1f} -> {b['y1']:>7.1f}  h={b['y1'] - b['y0']:>6.1f}  "
                  f"{b['color']}  {b['name']}")

        if p["cards"]:
            print("\n-- ROUNDED CARDS (inset panel on top of a band) --")
            for c in p["cards"]:
                print(f"   y {c['y0']:>7.1f} -> {c['y1']:>7.1f}  x {c['x0']:g}->{c['x1']:g}  "
                      f"w={c['w']:g}  {c['color']}  {c['name']}"
                      f"{'  (top+bottom halves rejoined)' if c.get('split') else ''}")

        if p["panels"]:
            print("\n-- SQUARE-CORNER INSET PANELS --")
            for c in p["panels"]:
                print(f"   y {c['y0']:>7.1f} -> {c['y1']:>7.1f}  x {c['x0']:g}->{c['x1']:g}  "
                      f"w={c['w']:g}  {c['color']}  {c['name']}")

        if p["images"]:
            print("\n-- IMAGES --")
            for im in p["images"]:
                print(f"   y {im['y0']:>7.1f} -> {im['y1']:>7.1f}  {im['w']:g}x{im['h']:g}")

        print("\n-- TEXT (size / line-height in CSS px) --")
        for t in p["lines"]:
            lh = f"{t['line_height']:g}" if t["line_height"] else "-"
            print(f"   y {t['y']:>7.1f}  {t['size']:>5g}px/{lh:<5}  {t['align']:<6} "
                  f"on {t['on']:<24} {t['color'] or '?':<8} {t['text'][:52]!r}")

    if pairs:
        print(f"\n{'=' * 78}\nDESKTOP <-> MOBILE TYPE SCALE  (inline style = desktop, class = mobile)")
        seen = set()
        for e in pairs:
            k = norm(e["text"])
            if k in seen:
                continue
            seen.add(k)
            d = e["desktop"]
            m = e["mobile"]
            msize = f"{m['size']:g}px" if m else "?"
            print(f"\n   {e['text'][:66]!r}")
            print(f"      desktop {d['size']:g}px/{d['line_height'] or '?'}   mobile {msize}"
                  f"   align={e['align']}  on={e['on']}  color={e['color'] or '?'}")
            line = f'      -> style="{e["css"]}"'
            if e.get("mobile_class"):
                line += f'   class="{e["mobile_class"]}"'
            print(line)
            for n in e["notes"]:
                print(f"      !  {n}")

    print(f"\n{'=' * 78}")
    print("REMINDERS")
    print(f"  * Web font weights that resolve to Smart: {WEB_FONT_WEIGHTS}. <600 falls back to")
    print("    Arial Regular, >=600 to Arial Bold. Never mix 600-900 in one element, and never")
    print("    mix 100-500 in one element - the fallback would flatten the hierarchy.")
    print("  * Mixed weight inside one line belongs on <strong>/<em>/<a>, not a bare <span>.")
    print("  * Headings need mso-line-height-rule:exactly; body copy does not.")
    print("  * A colored band or card in the report means the module variant must carry that")
    print("    background - do not flatten it to white.")
    print("  * Any inline background-color needs a paired background-image:linear-gradient(c,c).")


def main():
    # Figma's Type3 glyph mapping can emit characters outside the console
    # codepage; never let that kill the report.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser()
    ap.add_argument("desktop")
    ap.add_argument("--mobile")
    ap.add_argument("--pages", help="1-based page range, e.g. 1-3")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    def pages_of(path):
        doc = fitz.open(path)
        rng = range(doc.page_count)
        if args.pages:
            a, _, b = args.pages.partition("-")
            rng = range(int(a) - 1, min(int(b or a), doc.page_count))
        return [analyze_page(doc[i], i + 1) for i in rng]

    desktop_pages = pages_of(args.desktop)
    mobile_pages = pages_of(args.mobile) if args.mobile else []
    fs_classes = load_font_size_classes()
    pairs = pair_sizes(desktop_pages, mobile_pages, fs_classes) if mobile_pages else []

    if args.json:
        json.dump({"desktop": desktop_pages, "mobile": mobile_pages,
                   "type_scale": pairs, "font_size_classes": fs_classes},
                  sys.stdout, indent=2)
        print()
    else:
        print_report(desktop_pages, mobile_pages, pairs)


if __name__ == "__main__":
    main()
