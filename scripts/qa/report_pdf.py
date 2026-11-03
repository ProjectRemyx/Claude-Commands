"""Render qa-report.md as a styled PDF (qa-report.pdf) for /qa-email.

  python report_pdf.py qa/qa-report.md [--out qa/qa-report.pdf] [--keep-html]

No extra dependencies: a small Markdown-subset converter (headings, blockquote, tables,
lists, paragraphs, **bold**, `code`) builds a styled HTML page, then Microsoft Edge or
Chrome prints it headless. If no browser is found, the HTML is kept and its path printed.
"""
import argparse, html, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

STATUS = {  # token -> css class
    "FLAG": "flag", "FLAGGED": "flag", "WARN": "warn", "MANUAL": "manual",
    "PASS": "pass", "PASS*": "pass", "N/A": "na", "NA": "na",
}

CSS = """
@page { size: Letter; margin: 14mm 12mm 16mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Arial, Helvetica, sans-serif; color: #1f2933; font-size: 10.5px;
       line-height: 1.5; margin: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.banner { background: #003087; color: #fff; padding: 16px 20px 14px; border-radius: 8px; margin-bottom: 14px; }
.banner h1 { margin: 0 0 4px; font-size: 18px; font-weight: 700; letter-spacing: .2px; }
.banner .sub { font-size: 11px; opacity: .85; }
.inputs { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 0; }
.inputs span { background: rgba(255,255,255,.14); border-radius: 12px; padding: 2px 9px; font-size: 10px; }
.inputs span.no { background: rgba(255,255,255,.06); opacity: .7; text-decoration: line-through; }
.chips { display: flex; gap: 8px; margin: 0 0 16px; }
.chip { flex: 1; border-radius: 8px; padding: 9px 12px; color: #fff; }
.chip b { display: block; font-size: 22px; line-height: 1.1; }
.chip span { font-size: 10px; text-transform: uppercase; letter-spacing: .6px; opacity: .9; }
.chip.flag { background: #c62828; } .chip.warn { background: #d97706; } .chip.manual { background: #4b5b8c; }
.chip.pass { background: #2e7d32; } .chip.na { background: #8a949e; }
h2 { font-size: 14px; color: #003087; margin: 20px 0 8px; padding-bottom: 4px; border-bottom: 2px solid #ccecf9;
     break-after: avoid; }
h3 { font-size: 12px; color: #003087; margin: 14px 0 6px; break-after: avoid; }
p { margin: 0 0 8px; }
blockquote { margin: 0 0 14px; padding: 10px 14px; background: #fff8e1; border-left: 4px solid #ffb819;
             border-radius: 0 6px 6px 0; }
blockquote p { margin: 0; }
ul, ol { margin: 0 0 10px; padding-left: 20px; }
li { margin: 0 0 6px; break-inside: avoid; }
ul.blocking { list-style: none; padding: 0; }
ul.blocking li { background: #fdecec; border-left: 4px solid #c62828; border-radius: 0 6px 6px 0; padding: 7px 10px; }
.tag { display: inline-block; background: #003087; color: #fff; font-size: 9px; font-weight: 600;
       border-radius: 3px; padding: 1px 6px; margin-right: 4px; vertical-align: 1px; }
table { width: 100%; border-collapse: collapse; margin: 0 0 12px; font-size: 9.5px; }
thead { display: table-header-group; }
th { background: #003087; color: #fff; text-align: left; font-weight: 600; padding: 6px 8px; }
td { padding: 6px 8px; border-bottom: 1px solid #e4e7eb; vertical-align: top; }
tr { break-inside: avoid; }
tbody tr:nth-child(even) td { background: #f5f8fb; }
td.c-num { width: 34px; font-weight: 600; color: #52606d; white-space: nowrap; }
td.c-status { width: 70px; white-space: nowrap; }
.pill { display: inline-block; min-width: 54px; text-align: center; border-radius: 10px; padding: 1px 8px;
        font-size: 9px; font-weight: 700; letter-spacing: .4px; color: #fff; }
.pill.flag { background: #c62828; } .pill.warn { background: #d97706; } .pill.manual { background: #4b5b8c; }
.pill.pass { background: #2e7d32; } .pill.na { background: #8a949e; }
tr.row-flag td { background: #fdf1f1 !important; }
code { font-family: Consolas, "Courier New", monospace; font-size: .92em; background: #eef2f6;
       border-radius: 3px; padding: 0 3px; overflow-wrap: anywhere; }
strong { font-weight: 700; }
.foot { margin-top: 18px; font-size: 9px; color: #7b8794; border-top: 1px solid #e4e7eb; padding-top: 6px; }
"""


def inline(text):
    """Escape, then apply `code` and **bold** (code spans are protected from bold parsing)."""
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for p in parts:
        if len(p) > 1 and p.startswith("`") and p.endswith("`"):
            out.append(f"<code>{html.escape(p[1:-1])}</code>")
        else:
            e = html.escape(p, quote=False)
            e = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", e)
            out.append(e)
    return "".join(out)


def pill(cell):
    key = cell.strip().strip("*").upper() if cell.strip() not in STATUS else cell.strip()
    cls = STATUS.get(cell.strip().upper()) or STATUS.get(key)
    return f'<span class="pill {cls}">{html.escape(cell.strip())}</span>' if cls else None


def split_row(line):
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [c.replace("\\|", "|").strip() for c in cells]


def render_table(lines):
    head = split_row(lines[0])
    body = [split_row(l) for l in lines[2:]]
    status_col = next((i for i, h in enumerate(head) if h.lower() == "status"), None)
    num_col = 0 if head and head[0] == "#" else None
    out = ["<table><thead><tr>" + "".join(f"<th>{inline(h)}</th>" for h in head) + "</tr></thead><tbody>"]
    for r in body:
        r += [""] * (len(head) - len(r))
        flagged = status_col is not None and r[status_col].strip().upper() in ("FLAG", "FLAGGED")
        tds = []
        for i, c in enumerate(r[:len(head)]):
            if i == status_col:
                tds.append(f'<td class="c-status">{pill(c) or inline(c)}</td>')
            elif i == num_col:
                tds.append(f'<td class="c-num">{inline(c)}</td>')
            else:
                tds.append(f"<td>{inline(c)}</td>")
        out.append(f'<tr{" class=\"row-flag\"" if flagged else ""}>' + "".join(tds) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def render_list_item(text, ordered):
    m = re.match(r"(\*\*)?\[([^\]]+)\]\s*(.*)", text)
    if m and not ordered:  # "[#7 Figma] ..." or "**[#7 Figma] title** ..." -> tag badge
        rest = (m.group(1) or "") + m.group(3)
        return f'<li><span class="tag">{html.escape(m.group(2))}</span>{inline(rest)}</li>'
    return f"<li>{inline(text)}</li>"


def header_block(lines):
    """Turn the '# QA — …', 'Inputs:' and 'Result:' lines into the banner + count chips."""
    title, inputs, result = "", "", ""
    rest = []
    for l in lines:
        if l.startswith("# ") and not title:
            title = l[2:].strip()
        elif l.startswith("Inputs:") and not inputs:
            inputs = l[len("Inputs:"):].strip()
        elif l.startswith("Result:") and not result:
            result = l[len("Result:"):].strip()
        else:
            rest.append(l)
    t = title.split(" — ")
    out = ['<div class="banner">', f"<h1>{inline(t[0] + (' — ' + t[1] if len(t) > 1 else ''))}</h1>"]
    if len(t) > 2:
        out.append(f'<div class="sub">{inline(" — ".join(t[2:]))}</div>')
    if inputs:
        out.append('<div class="inputs">')
        for item in [i.strip() for i in inputs.split("·") if i.strip()]:
            no = "✗" in item
            out.append(f'<span class="{"no" if no else ""}">{inline(item)}</span>')
        out.append("</div>")
    out.append("</div>")
    if result:
        counts = re.findall(r"(\d+)\s+(FLAG|WARN|MANUAL|PASS|N/A)", result)
        if counts:
            out.append('<div class="chips">')
            for n, k in counts:
                out.append(f'<div class="chip {STATUS[k]}"><b>{n}</b><span>{k}</span></div>')
            out.append("</div>")
        extra = re.sub(r"(\d+\s+(FLAG|WARN|MANUAL|PASS|N/A)\s*·?\s*)", "", result).strip(" ·")
        if extra:
            out.append(f"<p>{inline(extra)}</p>")
    return "\n".join(out), rest


def md_to_html(md):
    lines = md.splitlines()
    head, lines = header_block(lines)
    out, i, section = [head], 0, ""
    while i < len(lines):
        l = lines[i]
        if not l.strip():
            i += 1; continue
        if l.startswith("### "):
            out.append(f"<h3>{inline(l[4:])}</h3>"); i += 1; continue
        if l.startswith("## "):
            section = l[3:].strip().lower()
            out.append(f"<h2>{inline(l[3:])}</h2>"); i += 1; continue
        if l.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip("> ").rstrip()); i += 1
            out.append("<blockquote><p>" + inline(" ".join(buf)) + "</p></blockquote>"); continue
        if l.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                buf.append(lines[i]); i += 1
            out.append(render_table(buf)); continue
        m = re.match(r"^\s*([-*]|\d+\.)\s+(.*)", l)
        if m:
            ordered = m.group(1)[0].isdigit()
            items = []
            while i < len(lines):
                m2 = re.match(r"^\s*([-*]|\d+\.)\s+(.*)", lines[i])
                if m2:
                    items.append(m2.group(2)); i += 1
                elif lines[i].startswith("  ") and lines[i].strip() and items:
                    items[-1] += " " + lines[i].strip(); i += 1
                else:
                    break
            tag = "ol" if ordered else "ul"
            cls = ' class="blocking"' if not ordered and section.startswith("blocking") else ""
            out.append(f"<{tag}{cls}>" + "".join(render_list_item(t, ordered) for t in items) + f"</{tag}>")
            continue
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|>|\s*\||\s*([-*]|\d+\.)\s)", lines[i]):
            buf.append(lines[i].strip()); i += 1
        out.append(f"<p>{inline(' '.join(buf))}</p>")
    return "\n".join(out)


def find_browser():
    cands = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in cands:
        if os.path.isfile(c):
            return c
    for name in ("msedge", "google-chrome", "chromium", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md")
    ap.add_argument("--out")
    ap.add_argument("--keep-html", action="store_true")
    a = ap.parse_args()
    md_path = Path(a.md).resolve()
    out = Path(a.out).resolve() if a.out else md_path.with_suffix(".pdf")
    body = md_to_html(md_path.read_text(encoding="utf-8"))
    title = md_path.parent.parent.name or "QA report"
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>QA — {html.escape(title)}</title>'
            f"<style>{CSS}</style></head><body>{body}"
            f'<div class="foot">Generated by /qa-email from {html.escape(md_path.name)}</div></body></html>')
    html_path = out.with_suffix(".html")
    html_path.write_text(page, encoding="utf-8")

    browser = find_browser()
    if not browser:
        print(f"No Edge/Chrome found — open and print to PDF manually: {html_path}")
        return 1
    with tempfile.TemporaryDirectory() as profile:  # isolated profile so an open browser window doesn't interfere
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run",
               f"--user-data-dir={profile}", f"--print-to-pdf={out}", html_path.as_uri()]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    if not out.exists() or out.stat().st_size == 0:
        print(f"PDF render failed — HTML kept at {html_path}")
        return 1
    if not a.keep_html:
        html_path.unlink()
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
