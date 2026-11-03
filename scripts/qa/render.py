#!/usr/bin/env python3
"""
render.py — optional screenshots of the build HTML for the Figma comparison.

  python render.py build.html --outdir qa/renders

Writes desktop-640.png, mobile-375.png, and *-darkpref.png (prefers-color-scheme: dark — this is
Apple Mail-style dark mode only; Gmail/Outlook force-invert and must be checked in Inbox Monster).
Chromium is NOT an email client: use these for layout/spacing vs Figma, not for client rendering.
Needs: pip install playwright && playwright install chromium
"""
import argparse, os, pathlib, sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("Playwright not installed — skip renders (pip install playwright && playwright install chromium)")

p = argparse.ArgumentParser()
p.add_argument("html")
p.add_argument("--outdir", default="qa/renders")
a = p.parse_args()
os.makedirs(a.outdir, exist_ok=True)
url = pathlib.Path(a.html).resolve().as_uri()
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for name, w, mobile in [("desktop-640", 640, False), ("mobile-375", 375, True)]:
        for scheme in ("light", "dark"):
            ctx = b.new_context(viewport={"width": w, "height": 900}, device_scale_factor=2 if mobile else 1,
                                is_mobile=mobile, color_scheme=scheme)
            pg = ctx.new_page()
            pg.goto(url, wait_until="networkidle", timeout=60000)
            out = os.path.join(a.outdir, f"{name}{'-darkpref' if scheme == 'dark' else ''}.png")
            pg.screenshot(path=out, full_page=True)
            print(out)
            ctx.close()
    b.close()
