#!/usr/bin/env python3
"""
email_qa.py — deterministic pre-R1 checks for SFMC HTML emails.

Used by the /qa-email Claude Code command. Runs every check that does not need
judgment, writes the full results to JSON, and prints a short summary so the
command spends tokens only on what needs a human (or Claude) to look at.

Usage
  python email_qa.py check --html build.html [--eml test-send.eml | --sent-html im-download.html] [--expected expected.json]
                           [--figma figma.pdf] [--out qa_results.json] [--offline] [--no-validate]
  python email_qa.py doc-text  jira-export.doc        # dump a Jira Word export as plain text

Status values: PASS | FLAG (definite issue) | WARN (likely issue, review) |
               MANUAL (needs a human / screenshot) | NA | INFO
Requires: beautifulsoup4, requests. Optional: Pillow (image checks), pypdf or pdfplumber (Figma copy diff).
"""
import argparse, concurrent.futures as cf, difflib, email, json, os, re, subprocess, sys, unicodedata
from email import policy
from urllib.parse import urlsplit, parse_qsl, unquote

try:
    from bs4 import BeautifulSoup, Comment, Tag
except ImportError:
    sys.exit("Missing dependency: pip install beautifulsoup4 requests pillow pypdf")
try:
    import requests
except ImportError:
    requests = None
try:
    from PIL import Image
    import io
except ImportError:
    Image = None

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
BLOCK_TAGS = {"td", "th", "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "div"}
RESULTS = []
RESULTS_EXTRA = {}


# ----------------------------------------------------------------------------- helpers
def add(cid, title, status, details=None, spec=None, rows=None):
    RESULTS.append({"id": cid, "title": title, "status": status, "details": details or [],
                    "spec": spec or [], "checklist_rows": rows or []})


def style_of(el):
    s = (el.get("style") or "") if isinstance(el, Tag) else ""
    return {k.strip().lower(): v.strip().lower() for k, v in
            (d.split(":", 1) for d in s.split(";") if ":" in d)}


def norm(t):
    t = unicodedata.normalize("NFKC", t or "")
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", "-").replace(" ", " ").replace("‌", "").replace("͏", "")
    return re.sub(r"\s+", " ", t).strip().lower()


def squash(t):
    return re.sub(r"[\s\W_]+", "", norm(t))


def is_hidden(el):
    st = style_of(el)
    return st.get("display") == "none" or st.get("mso-hide") == "all" or \
        (st.get("max-height", "").startswith("0") and st.get("overflow") == "hidden")


def ancestors_hidden(el):
    return any(isinstance(p, Tag) and is_hidden(p) for p in [el, *el.parents])


AMP_BLOCK = re.compile(r"%%\[.*?\]%%", re.S)
AMP_INLINE = re.compile(r"%%=.*?=%%", re.S)
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿\U0001F1E6-\U0001F1FF‍️]")


# ----------------------------------------------------------------------------- loading
def load_eml(path):
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    html = None
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            html = part.get_content()
            break
    return msg, html


def load_expected(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pdf_text(path):
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except ImportError:
        pass
    try:
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    except ImportError:
        pass
    try:
        return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return None


def doc_text(path):
    raw = open(path, "rb").read()
    head = raw[:4000].lower()
    if b"<html" in head or b"<table" in head or raw.lstrip()[:1] == b"<":
        soup = BeautifulSoup(raw.decode("utf-8", "ignore"), "html.parser")
        for t in soup(["style", "script"]):
            t.decompose()
        lines = []
        for tr in soup.find_all("tr"):  # Jira exports field: value as table rows
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"], recursive=False)]
            if any(cells):
                lines.append(" | ".join(cells))
        body = soup.get_text("\n", strip=True)
        return ("\n".join(lines) + "\n\n---- FULL TEXT ----\n" + body) if lines else body
    for tool in (["antiword", path], ["catdoc", path]):
        try:
            return subprocess.run(tool, capture_output=True, text=True).stdout
        except FileNotFoundError:
            continue
    try:
        import docx  # if it is really a .docx renamed
        return "\n".join(p.text for p in docx.Document(path).paragraphs)
    except Exception:
        return "Could not extract text: binary .doc and no antiword/catdoc available. Save the Jira export as HTML or .docx."


# ----------------------------------------------------------------------------- network
def fetch(url, want_body=False):
    if requests is None:
        return {"url": url, "error": "requests not installed"}
    try:
        r = requests.get(url, headers=UA, timeout=15, allow_redirects=True, stream=True)
        out = {"url": url, "status": r.status_code, "final": r.url,
               "chain": [h.url for h in r.history] + [r.url], "type": r.headers.get("content-type", "")}
        if want_body:
            out["body"] = r.raw.read(6_000_000, decode_content=True)
        r.close()
        return out
    except Exception as e:
        return {"url": url, "error": str(e)[:160]}


def pmap(fn, items):
    with cf.ThreadPoolExecutor(8) as ex:
        return list(ex.map(fn, items))


# ----------------------------------------------------------------------------- checks
def check_ampscript(raw, rendered_html):
    issues, warns = [], []
    if raw.count("%%[") != raw.count("]%%"):
        issues.append(f"Unbalanced AmpScript blocks: {raw.count('%%[')} '%%[' vs {raw.count(']%%')} ']%%'")
    if raw.count("%%=") != raw.count("=%%"):
        issues.append(f"Unbalanced inline AmpScript: {raw.count('%%=')} '%%=' vs {raw.count('=%%')} '=%%'")
    for pat, msg in [(r"%%\s+\[", "space between %% and ["), (r"\]\s+%%", "space between ] and %%"),
                     (r"%%\s+=", "space between %% and ="), (r"=\s+%%", "space between = and %%"),
                     (r"%%\s+[A-Za-z_]+\s*%%|%%[A-Za-z_]+\s+%%", "space inside a %%Attribute%% string")]:
        for m in re.finditer(pat, raw):
            issues.append(f"Stray space ({msg}): …{raw[max(0, m.start()-25):m.end()+25].strip()}…")
    code = "\n".join(AMP_BLOCK.findall(raw) + AMP_INLINE.findall(raw))
    for ch, name in [(" ", "non-breaking space"), ("“", "smart quote “"), ("”", "smart quote ”"),
                     ("‘", "smart quote ‘"), ("’", "smart quote ’"), ("​", "zero-width space")]:
        if ch in code:
            issues.append(f"{name} inside AmpScript (copied from Word/Jira?) — breaks silently")
    c = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    ifs = len(re.findall(r"\bIF\b", c, re.I))  # \b excludes ENDIF/ELSEIF
    endifs = len(re.findall(r"\bENDIF\b", c, re.I))
    if ifs != endifs:
        issues.append(f"IF/ENDIF mismatch: {ifs} IF vs {endifs} ENDIF")
    if len(re.findall(r"\bFOR\b", c, re.I)) != len(re.findall(r"\bNEXT\b", c, re.I)):
        issues.append("FOR/NEXT mismatch")
    declared = {v.lower() for v in re.findall(r"\b(?:SET|VAR)\s+(@\w+)", c, re.I)}
    declared |= {v.lower() for v in re.findall(r"VAR\s+([@\w ,]+)", c, re.I) for v in re.findall(r"@\w+", v)}
    used = {v.lower() for v in re.findall(r"@\w+", c)}
    undeclared = sorted(used - declared)
    if undeclared:
        warns.append("Variables used but never SET/VAR'd: " + ", ".join(undeclared))
    fname_vars = [v for v in declared if re.search(r"first|fname", v)]
    if fname_vars and not re.search(r"Empty\s*\(|IsNull\s*\(|IIF\s*\(", c, re.I):
        warns.append(f"First-name variable(s) {fname_vars} with no Empty()/IIF fallback found")
    attrs = sorted(set(re.findall(r"%%([A-Za-z_][\w ]*)%%", raw)))
    if rendered_html:
        txt = BeautifulSoup(rendered_html, "html.parser").get_text(" ")
        for pat, msg in [(r"%%", "leftover %% in rendered test send"), (r"\bv\(@", "raw v(@…) in rendered test send"),
                         (r"\b(Hi|Hello|Dear|Hey)\s*[,!]", "greeting with empty name in rendered test send")]:
            if re.search(pat, txt):
                issues.append(msg)
    info = [f"{len(AMP_BLOCK.findall(raw))} AmpScript blocks, {len(AMP_INLINE.findall(raw))} inline expressions",
            f"Variables declared: {', '.join(sorted(declared)) or 'none'}",
            f"Personalization strings: {', '.join(attrs) or 'none'}"]
    status = "FLAG" if issues else ("WARN" if warns else ("PASS" if code else "NA"))
    add("ampscript", "AmpScript syntax & personalization", status, issues + warns + info, [6],
        ["Ampscript inspected"])
    return {v.lower(): s for v, s in re.findall(r"SET\s+(@\w+)\s*=\s*['\"]([^'\"]*)['\"]", c, re.I)}


def resolve_href(href, amp_vars):
    m = re.match(r"%%=\s*RedirectTo\s*\(\s*(@\w+)\s*\)\s*=%%", href or "", re.I)
    if m:
        return amp_vars.get(m.group(1).lower(), href)
    m = re.match(r"%%=\s*RedirectTo\s*\(\s*['\"]([^'\"]+)['\"]\s*\)\s*=%%", href or "", re.I)
    return m.group(1) if m else href


def classify(href):
    h = (href or "").strip()
    if not h or h == "#":
        return "empty"
    lo = h.lower()
    if lo.startswith("tel:"): return "tel"
    if lo.startswith("mailto:"): return "mailto"
    if lo.startswith(("http://", "https://")): return "web"
    if "%%" in h: return "ampscript"
    return "other"


def is_button(a):
    st = style_of(a)
    if any(k in st for k in ("background", "background-color", "border", "padding")) or st.get("display") in ("block", "inline-block"):
        return True
    td = a.find_parent("td")
    if td is not None and (td.get("bgcolor") or "background" in (td.get("style") or "")):
        if len(td.get_text(strip=True)) == len(a.get_text(strip=True)):
            return True
    return False


def underlined(a):
    if "underline" in (a.get("style") or ""):
        return True
    return any("underline" in (c.get("style") or "") or c.name == "u" for c in a.find_all(True))


def _w640(el):
    return bool(re.search(r"width\s*:\s*640px", el.get("style") or "", re.I))


def find_regions(soup):
    """Locate the shared header and footer so body-only rules can skip them. Either may be None (e.g. a body-only file).
    Header = the 640px table holding SharedTop03's <!-- Right Blue Bar --> comment.
    Footer = the first 640px table containing an Unsubscribe / Email Preferences link (SharedBtm01 + legal + SharedBtm02)."""
    header = None
    c = soup.find(string=lambda s: isinstance(s, Comment) and "right blue bar" in s.lower())
    if c is not None:
        header = next((t for t in c.parents if getattr(t, "name", None) == "table" and _w640(t)), None)
    footer = None
    unsub = lambda x: x.name == "a" and re.search(r"unsubscribe|email preferences", x.get_text(" ", strip=True), re.I)
    for t in soup.find_all("table"):
        if _w640(t) and t.find(unsub) and not (header is not None and t in header.parents):
            footer = t
            break
    return header, footer


def is_footer_nav(a, region):
    """SharedBtm01's footer nav (My Account, Contact Us, … Unsubscribe): each link sits in a <p> with text-transform:uppercase.
    The nav is not underlined by design; the footer's legal links (required legal, disclaimers) are not in such a <p>."""
    p = a.find_parent("p")
    return region == "footer" and p is not None and style_of(p).get("text-transform") == "uppercase"


def region_of(el, regions):
    header, footer = regions
    for p in (el, *el.parents):
        if header is not None and p is header:
            return "header"
        if footer is not None and p is footer:
            return "footer"
    return "body"


TRACKED = re.compile(r"^https?://click\.[^/]+/\?qs=", re.I)  # SFMC click-tracking redirect
SFMC_APPENDED = ("ajs_uid", "activity_id")  # SFMC web-analytics params; everything from the first of these on is appended at send


def strip_sfmc(url):
    """Drop the params SFMC appends at send (ajs_uid, activity_id, and the utm_source=salesforce/utm_medium=email after them)."""
    return re.sub(r"[?&](?:%s)=.*$" % "|".join(SFMC_APPENDED), "", url)  # string cut keeps the original encoding


def find_legal_start(soup, order):
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        if re.search(r"legal|disclaimer|footer", c, re.I):
            return order.get(id(c), 10**9), f"HTML comment <!--{c.strip()[:40]}-->"
    for el in soup.find_all(BLOCK_TAGS):
        if el.find(BLOCK_TAGS):
            continue
        t = el.get_text(" ", strip=True)
        if re.match(r"^(\d{1,2}\s?[A-Z]|\*\s?[A-Z]|©)", t) and len(t) > 40:
            return order.get(id(el), 10**9), f"first disclaimer-like block: “{t[:50]}…”"
    return 10**9, "not found"


def check_links(soup, raw, amp_vars, expected, order, offline, legal_pos, legal_how, regions=(None, None)):
    links = []
    for a in soup.find_all("a"):
        href = a.get("href")
        res = resolve_href(href, amp_vars)
        kind = classify(res)
        img = a.find("img")
        text = a.get_text(" ", strip=True)[:60] or (f"[img alt: {img.get('alt')}]" if img else "")
        region = region_of(a, regions)
        links.append({"text": text,
                      "href": href, "resolved": res, "kind": kind, "target": a.get("target"),
                      "image": bool(a.find("img")), "button": is_button(a), "underlined": underlined(a),
                      "region": region, "footer_nav": is_footer_nav(a, region),
                      "legal_region": order.get(id(a), 0) >= legal_pos, "alias": a.get("alias"), "_el": a})
    flags, warns = [], []
    # redirects first, so SFMC click-tracked links (post-send HTML) can be checked against their real destination
    redirect_rows = []
    if not offline:
        uniq = sorted({l["resolved"] for l in links if l["kind"] == "web"})
        for res in pmap(fetch, uniq):
            redirect_rows.append(res)
            if "error" in res:
                warns.append(f"Could not open {res['url'][:90]}: {res['error']}")
            elif res["status"] >= 400:
                flags.append(f"HTTP {res['status']}: {res['url'][:90]}")
            else:
                sent = {k: v for k, v in parse_qsl(urlsplit(res["url"]).query) if k.startswith("utm_")}
                kept = dict(parse_qsl(urlsplit(res["final"]).query))
                lost = [k for k, v in sent.items() if kept.get(k) != v]
                if lost and res["final"] != res["url"]:
                    warns.append(f"Redirect dropped/changed {', '.join(lost)}: {res['url'][:70]} → {res['final'][:70]}")
    first_hop = {r["url"]: r["chain"][1] for r in redirect_rows if len(r.get("chain") or []) > 1}
    untracked = 0
    for l in links:
        r = l["resolved"] or ""
        if l["kind"] == "web" and TRACKED.match(r):
            if r in first_hop:
                l["dest"] = strip_sfmc(first_hop[r])
            else:
                untracked += 1
        l.setdefault("dest", r)
    if untracked:
        warns.append(f"{untracked} click-tracked links could not be resolved (offline or blocked) — UTM checks skipped for them")
    for l in links:
        h, r = l["href"] or "", l["resolved"] or ""
        r = l["dest"] if l["kind"] == "web" else r
        tag = f"[{l['text'][:35]}] {r[:90]}"
        if l["kind"] == "empty":
            flags.append(f"Empty or # href: {tag}")
        if l["kind"] == "web":
            if l["target"] != "_blank":
                flags.append(f"Missing target=_blank: {tag}")
        if l["kind"] == "web" and not TRACKED.match(r):  # an unresolved tracked link has no meaningful query to check
            if r.lower().startswith("http://"):
                warns.append(f"http not https (OK only for legal display URLs): {tag}")
            if " " in r:
                flags.append(f"Unencoded space in URL: {tag}")
            if r.count("?") > 1:
                flags.append(f"More than one '?': {tag}")
            if "&&" in r or "?&" in r:
                flags.append(f"Malformed query separators: {tag}")
            if "#" in r and "?" in r and r.index("#") < r.index("?"):
                flags.append(f"Fragment before query string — SFMC tracking/UTMs land after the #: {tag}")
            q = parse_qsl(urlsplit(r).query, keep_blank_values=True)
            keys = [k for k, _ in q]
            dups = {k for k in keys if keys.count(k) > 1}
            if dups:
                l["dup_keys"] = sorted(dups)
            has_utm = any(k.startswith("utm_") for k in keys)
            if l["region"] != "body" and has_utm:
                # header/footer are the same for every campaign — only body content is tracked
                flags.append(f"UTMs on {l['region']} link — header/footer links must carry no UTMs: {tag}")
            elif l["legal_region"] and has_utm and r.split("?")[0] not in l["text"]:
                flags.append(f"UTMs in legal region link (display text isn't the URL): {tag}")
            exp_utm = expected.get("utm") or {}
            # with a Jira URL table, the per-URL comparison below is more precise — don't report each mismatch twice
            if exp_utm and not expected.get("urls") and l["region"] == "body" and not l["legal_region"]:
                got = {}
                for k, v in q:
                    got.setdefault(k, v)
                bad = [f"{k}={got.get(k)!r} (expected {v!r})" for k, v in exp_utm.items() if v and got.get(k) != v]
                if bad:
                    flags.append(f"UTM mismatch {tag}: " + "; ".join(bad))
        if l["kind"] in ("tel", "mailto") and l["target"] == "_blank":
            flags.append(f"{l['kind']} link should not have target=_blank: {tag}")
        if l["kind"] == "tel" and not re.fullmatch(r"tel:(\+1)?(\d{3}-\d{3}-\d{4}|\d{10})", r.strip(), re.I):
            flags.append(f"tel format not tel:###-###-#### / tel:########## / tel:+1###-###-####: {r}")
        if l["kind"] == "mailto" and not re.fullmatch(r"mailto:[^@\s]+@[^@\s]+\.[a-z]{2,}(\?.*)?", r.strip(), re.I):
            flags.append(f"mailto format looks wrong: {r}")
        if l["kind"] == "ampscript" and r == h and "RedirectTo" in h:
            warns.append(f"Could not resolve AmpScript href statically, check in test send: {h[:80]}")
        if not l["image"] and not l["button"] and not l["footer_nav"] \
                and l["kind"] in ("web", "tel", "mailto", "ampscript") and not l["underlined"]:
            flags.append(f"Text link not underlined: {tag}")
    # expected URL list from Jira
    exp_urls = expected.get("urls") or []
    def base(u): s = urlsplit(u); return (s.netloc.lower().replace("www.", "") + s.path.rstrip("/")).lower()
    if exp_urls:
        # the Jira URL table only covers body content; header/footer links are shared and untracked
        web = [l for l in links if l["kind"] == "web" and l["region"] == "body" and not TRACKED.match(l["dest"])]
        for e in exp_urls:
            eu = e["url"] if isinstance(e, dict) else e
            label = (e.get("label", "") + " ") if isinstance(e, dict) else ""
            matches = [l for l in web if base(l["dest"]) == base(eu)]
            if not matches:
                flags.append(f"Expected URL not found in email: {label}{eu[:100]}")
                continue
            eq = dict(parse_qsl(urlsplit(eu).query, keep_blank_values=True))
            # several placements can share a path (hero image + hero CTA) — compare against the closest one only
            want = "image" if re.search(r"\bimage\b", label, re.I) else \
                   "button" if re.search(r"\b(cta|button)\b", label, re.I) else \
                   "text" if re.search(r"\btext\b", label, re.I) else None
            kind_of = lambda l: "image" if l["image"] else ("button" if l["button"] else "text")
            diffs = []
            for m in matches:
                gq = dict(parse_qsl(urlsplit(m["dest"]).query, keep_blank_values=True))
                diffs.append(([f"{k}: got {gq.get(k)!r} expected {v!r}" for k, v in eq.items() if gq.get(k) != v], m))
            # fewest differing params; on a tie prefer the same kind of clickable (image / button / text) as the Jira row
            diff, m = min(diffs, key=lambda x: (len(x[0]), 0 if want and kind_of(x[1]) == want else 1))
            if diff:
                flags.append(f"Params differ from Jira for {label}[{m['text'][:30]}]: " + "; ".join(diff))
        exp_bases = {base(e["url"] if isinstance(e, dict) else e) for e in exp_urls}
        extra = sorted({base(l["dest"]) for l in web if base(l["dest"]) not in exp_bases and not l["legal_region"]})
        if extra:
            warns.append("Links in body not on the Jira URL list: " + ", ".join(extra[:15]))
    status = "FLAG" if flags else ("WARN" if warns else "PASS")
    add("links", "URLs, UTMs, target, tel/mailto, underline", status,
        flags + warns + [f"{len(links)} links; legal region start detected by {legal_how}"], [9],
        ["Web URLs reviewed", "No unencoded spaces", "Redirect accuracy", "Query string syntax", "No UTMs in legal",
         "open in a new tab", "begin with https", "Tel links", "Mailto links", "Clickable email text underlined",
         "Phone numbers underlined"])
    return links, redirect_rows


def check_phone_text(soup):
    hits = []
    for s in soup.find_all(string=re.compile(r"(\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b|\b1-8\d\d-[A-Z0-9-]{7,})")):
        if not s.find_parent("a"):
            hits.append(s.strip()[:80])
    add("phone_text", "Phone numbers coded as tel: links", "FLAG" if hits else "PASS",
        [f"Phone number not linked: {h}" for h in hits], [9], ["Phone numbers underlined"])


def check_unsub(links, msg, expected):
    un = [l for l in links if re.search(r"unsub|opt.?out|subscription.?center|profile.?center|preferences", (l["text"] or "") + " " + (l["href"] or ""), re.I)]
    d = [f"{l['text'][:40]} → {l['href'][:80]}" for l in un]
    status = "PASS" if un else "FLAG"
    if not un:
        d.insert(0, "No unsubscribe / preference link found")
    if msg is not None:
        lu, lup = msg.get("List-Unsubscribe"), msg.get("List-Unsubscribe-Post")
        d.append(f"List-Unsubscribe header: {'present' if lu else 'MISSING'}; one-click (List-Unsubscribe-Post): {'present' if lup else 'missing'}")
        if not lu:
            status = "FLAG"
    if expected.get("bread_legal") and len(un) < 2:
        status = "FLAG"; d.append("Credit-card (Bread) email needs the extra unsubscribe link")
    d.append("Functional unsubscribe (actually processing) must be confirmed manually on a test send.")
    add("unsubscribe", "Unsubscribe link", status, d, [10], ["Bread legal + extra unsubscribe"])


HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def _is_heading(el):
    if el.name in HEADING_TAGS:
        return True
    fw = style_of(el).get("font-weight", "")
    return el.name == "p" and (fw in ("bold", "bolder") or (fw.isdigit() and int(fw) >= 600)) \
        and len(el.get_text(" ", strip=True)) <= 80


def icon_text_beside(img):
    """Text blocks next to an icon: the other cells of its row, else (stacked layout) its own cell or the next row."""
    td = img.find_parent(["td", "th"])
    if td is None:
        return []
    tr = td.find_parent("tr")
    scopes = [c for c in (tr.find_all(["td", "th"], recursive=False) if tr else []) if c is not td and c.get_text(strip=True)]
    if not scopes:
        if td.get_text(strip=True):
            scopes = [td]
        elif tr is not None and tr.find_next_sibling("tr") is not None:
            scopes = [tr.find_next_sibling("tr")]
    return scopes


def icon_alt_verdict(img):
    """alt="" on an icon is only OK when the text beside it has a heading AND body copy."""
    heads = bodies = 0
    for s in icon_text_beside(img):
        blocks = [b for b in s.find_all(list(HEADING_TAGS) + ["p"]) if b.get_text(strip=True)]
        if not blocks:
            bodies += 1
        for b in blocks:
            if _is_heading(b):
                heads += 1
            elif not b.find_parent(list(HEADING_TAGS)):
                bodies += 1
    if heads and bodies:
        return None
    return "only a heading" if heads else ("only body copy" if bodies else "no text")


def check_images(soup, offline, regions=(None, None)):
    imgs = soup.find_all("img")
    flags, warns, inv = [], [], []
    urls = sorted({i.get("src") for i in imgs if (i.get("src") or "").startswith("http")})
    fetched = {} if offline else {r["url"]: r for r in pmap(lambda u: fetch(u, want_body=True), urls)}
    attr_dims = 0
    for i in imgs:
        src, alt = i.get("src") or "", i.get("alt")
        st = style_of(i)
        a = i.find_parent("a")
        href = (a.get("href") or "").lower() if a else ""
        name = src.rsplit("/", 1)[-1][:50]
        region = region_of(i, regions)
        row = {"src": src, "alt": alt, "linked": bool(a), "style_width": st.get("width"), "hidden_ancestor": ancestors_hidden(i),
               "region": region}
        if i.get("width") or i.get("height"):
            attr_dims += 1
        if alt is None:
            flags.append(f"Missing alt attribute: {name}")
        elif a and not alt.strip():
            flags.append(f"Linked image with empty alt: {name}")
        # alt text inherits text-decoration from the wrapping <a>, which is where the boilerplate puts the underline
        if a and alt and "underline" not in st.get("text-decoration", "") and "underline" not in style_of(a).get("text-decoration", ""):
            flags.append(f"Clickable image alt not underlined: {name} (alt “{alt[:30]}”)")
        if not a and "underline" in st.get("text-decoration", ""):
            flags.append(f"Non-clickable image has underlined alt: {name}")
        if alt and alt.strip() and not (st.get("color") and st.get("font-size")):
            warns.append(f"No alt-text color/font-size styling: {name}")
        if href.startswith("tel:") and alt and alt.strip() != "Call" and len(alt) < 25:
            warns.append(f"Tel button icon alt should be “Call”: {name} has “{alt}”")
        if href.startswith("mailto:") and alt and alt.strip() != "Email" and len(alt) < 25:
            warns.append(f"Mailto button icon alt should be “Email”: {name} has “{alt}”")
        if re.search(r"star", src, re.I) and alt != "5 out of 5 stars":
            warns.append(f"Star graphic alt should be “5 out of 5 stars”: {name} has “{alt}”")
        try:
            w = int(re.sub(r"\D", "", st.get("width", "") or str(i.get("width") or "")) or 0)
        except ValueError:
            w = 0
        if region == "body" and w and w <= 48 and alt is not None and not re.fullmatch(r"\d+|bullet|", alt.strip(), re.I):
            warns.append(f"Small icon ({w}px) alt is “{alt}” — numbered/bullet icons should be the number or “bullet”")
        # decorative icon (not a spacer, pixel, or header/footer art) with alt=""
        h_attr = int(re.sub(r"\D", "", str(i.get("height") or "")) or 0)
        if region == "body" and alt is not None and not alt.strip() and not a and not row["hidden_ancestor"] \
                and 16 <= w <= 150 and h_attr != 1:
            why = icon_alt_verdict(i)
            row["icon_alt_ok"] = why is None
            if why:
                flags.append(f"Icon {name} has alt=\"\" but the text beside it is {why} — alt=\"\" is only OK next to "
                             f"a heading + body copy; otherwise use the number or “bullet”")
        if src and not src.startswith("https://") and "%%" not in src:
            flags.append(f"Image src not https: {src[:80]}")
        f = fetched.get(src)
        if f:
            if "error" in f or f.get("status", 0) >= 400:
                flags.append(f"Image does not load ({f.get('status') or f.get('error')}): {src[:80]}")
            elif Image and f.get("body"):
                try:
                    im = Image.open(io.BytesIO(f["body"]))
                    row.update(natural=im.size, fmt=im.format, kb=round(len(f["body"]) / 1024, 1),
                               frames=getattr(im, "n_frames", 1))
                    if im.mode in ("RGBA", "LA", "P") and im.format == "PNG":
                        rgba = im.convert("RGBA")
                        alpha = rgba.getchannel("A")
                        if alpha.getextrema()[0] < 255:
                            px = [p for p in rgba.getdata() if p[3] > 200]
                            whiteish = px and sum(1 for p in px if min(p[:3]) > 230) / len(px) > 0.9
                            row["transparent"] = True
                            row["white_art"] = bool(whiteish)
                    if w and im.size[0] < w:
                        warns.append(f"Image narrower than display width ({im.size[0]}px < {w}px, will blur): {name}")
                    elif w and im.size[0] < 2 * w and im.format != "GIF":
                        row["note"] = "not 2x retina"
                    if row["kb"] > 1000:
                        warns.append(f"Large image {row['kb']}KB: {name}")
                    if row["frames"] > 1:
                        row["note"] = (row.get("note", "") + f" animated GIF {row['frames']} frames — Outlook desktop shows frame 1 only").strip()
                except Exception as e:
                    row["note"] = f"could not decode: {e}"[:80]
        inv.append(row)
    if attr_dims:
        warns.append(f"{attr_dims} <img> use HTML width/height attributes — team standard is width/height in inline CSS")
    add("images", "Images & alt text", "FLAG" if flags else ("WARN" if warns else "PASS"), flags + warns, [7, 11],
        ["Only clickable images contain underlined alt text", "Alt text color and size", "Icons have appropriate alt text",
         "Alt text matches the specified copy"])
    return inv


def check_preheader(soup, expected):
    pre = None
    for el in soup.body.find_all(True) if soup.body else []:
        idattr = " ".join(el.get("class", [])) + " " + (el.get("id") or "")
        if ("preheader" in idattr.lower() or is_hidden(el)) and el.get_text(strip=True):
            pre = el
            break
    if pre is None:
        add("preheader", "Preview text", "FLAG", ["No hidden preheader element found"], [3])
        return None
    raw = pre.get_text()
    text = re.split(r"[‌͏  ­]{2,}|(?:&zwnj;)", raw)[0].strip()
    filler = bool(re.search(r"[‌͏ ­]", raw)) or "&#847;" in str(pre) or "&zwnj;" in str(pre)
    d = [f"Preview text found: “{text}”", f"Filler spacing after preview text: {'yes' if filler else 'NO — body copy may leak into the preview'}"]
    status = "PASS" if filler else "WARN"
    if expected.get("preheader"):
        if norm(text) != norm(expected["preheader"]):
            status = "FLAG"; d.append(f"Expected (Jira): “{expected['preheader']}”")
    else:
        status = "MANUAL" if status == "PASS" else status; d.append("No expected preview text supplied")
    if len(text) > 140:
        d.append(f"{len(text)} chars — most clients show ~40–130")
    add("preheader", "Preview text", status, d, [3])
    return pre


def check_subject(soup, msg, expected):
    subj = str(msg.get("Subject")) if msg is not None and msg.get("Subject") else None
    src = "test-send .eml"
    if not subj:
        t = soup.find("title")
        subj, src = (t.get_text(strip=True) if t else None), "<title> tag (SFMC subject lives in email properties)"
    d = [f"Subject from {src}: “{subj}”"] if subj else ["No subject available — provide a test-send .eml or SFMC screenshot"]
    status = "MANUAL"
    exp = expected.get("subject")
    if subj and exp:
        pat = "^" + ".*".join(re.escape(norm(x)) for x in re.split(r"%%[^%]+%%", exp)) + "$"
        if "%%" in exp and msg is None:
            d.append(f"Expected subject has personalization ({exp}); verify render on a test send")
        elif "%%" in exp and re.match(pat, norm(subj)):
            status = "PASS"; d.append(f"Matches Jira subject with personalization rendered ({exp})")
        elif norm(subj) == norm(exp):
            status = "PASS" if src.startswith("test") else "WARN"
            if status == "WARN":
                d.append("Matches <title>; confirm the SFMC subject field too")
        else:
            status = "FLAG"; d.append(f"Expected (Jira): “{exp}”")
    if subj and len(subj) > 60:
        d.append(f"{len(subj)} chars — may truncate on mobile (~35–45 visible)")
    if msg is not None:
        d.append(f"From: {msg.get('From')}")
        if expected.get("from_name") and norm(expected["from_name"]) not in norm(str(msg.get("From"))):
            status = "FLAG"; d.append(f"From name expected: {expected['from_name']}")
    add("subject", "Subject line & from name", status, d, [2])
    return subj


def check_campaign_and_date(links, raw, expected):
    camps = sorted({dict(parse_qsl(urlsplit(l["resolved"] or "").query)).get("utm_campaign") for l in links if l["kind"] == "web"} - {None})
    d = [f"utm_campaign values in email: {', '.join(camps) or 'none'}"]
    status = "MANUAL"
    exp = expected.get("campaign_name")
    if exp:
        d.append(f"Expected campaign (Jira): {exp}")
        if camps and all(squash(exp) in squash(c) or squash(c) in squash(exp) for c in camps):
            d.append("utm_campaign values are consistent with the campaign name")
        elif camps:
            status = "WARN"; d.append("utm_campaign doesn't obviously match the campaign name — compare with the Jira URL tab")
    d.append("SFMC email/send name itself is not in the HTML — confirm in SFMC (or send a screenshot of the Send/Journey activity)")
    add("campaign", "Campaign name", status, d, [1])
    sd = expected.get("send_date")
    dd = [f"Expected send date (Jira): {sd or 'not supplied'}",
          "Scheduled date lives in SFMC (Journey / Send Definition) — not checkable from HTML. Screenshot needed."]
    if sd:
        y, m, dday = (sd.split("-") + ["", "", ""])[:3]
        codes = [f"{y}{m}{dday}", f"{m}{dday}{y[2:]}", f"{y[2:]}{m}{dday}", f"{m}{dday}"]
        found = [c for c in codes if c and c in raw]
        dd.append(f"Date codes found in HTML/URLs: {', '.join(found) or 'none'}")
        years = set(re.findall(r"©\s*(\d{4})", raw))
        if years and y not in years:
            dd.append(f"© year {', '.join(years)} differs from send year {y}")
    add("send_date", "Send date", "MANUAL", dd, [4])


def check_ab(raw, expected, other_versions):
    if not expected.get("ab_test") and not other_versions:
        add("ab", "A/B test setup", "NA", ["Jira does not mark this as an A/B test"], [5]); return
    d = ["Split %, winner criteria, duration and send window are SFMC settings — needs a screenshot or human check."]
    if expected.get("ab_variants"):
        d.append("Expected variants (Jira): " + json.dumps(expected["ab_variants"])[:300])
    for path in other_versions:
        other = open(path, encoding="utf-8", errors="ignore").read()
        sm = difflib.SequenceMatcher(None, raw, other, autojunk=False)
        changes = [op for op in sm.get_opcodes() if op[0] != "equal"]
        d.append(f"vs {os.path.basename(path)}: {len(changes)} differing regions")
        for op, i1, i2, j1, j2 in changes[:8]:
            d.append(f"  {op}: “{raw[i1:i2][:60].strip()}” → “{other[j1:j2][:60].strip()}”")
    if re.search(r"BeginImpressionRegion", raw):
        d.append("Impression regions present — remember SFMC A/B Test can't report on them; confirm the test variable is subject/content as intended")
    add("ab", "A/B test setup", "MANUAL", d, [5])


def leaf_blocks(soup, skip=None):
    out = []
    for el in soup.body.find_all(BLOCK_TAGS) if soup.body else []:
        if el.find(BLOCK_TAGS) or (skip is not None and (el is skip or skip in el.parents)):
            continue
        t = el.get_text(" ", strip=True)
        t = AMP_INLINE.sub("", t)
        if len(t) >= 3 and re.search(r"[A-Za-z]", t):
            out.append((el, t))
    return out


def check_copy_vs_figma(blocks, figma_path):
    if not figma_path:
        add("figma_copy", "Copy vs Figma", "MANUAL", ["No Figma PDF supplied"], [7], ["Coded copy matches the asset", "Email matches Figma 1:1"]); return
    txt = pdf_text(figma_path)
    if not txt or not txt.strip():
        add("figma_copy", "Copy vs Figma", "MANUAL", ["Figma PDF has no text layer (outlined text?) — compare visually"], [7]); return
    pdf_sq = squash(txt)
    pdf_lines = [l for l in (x.strip() for x in txt.splitlines()) if len(l) > 3]
    windows = [" ".join(pdf_lines[i:i + n]) for n in (1, 2, 3) for i in range(len(pdf_lines))]
    misses = []
    for _, t in blocks:
        if squash(t) and squash(t) not in pdf_sq:
            best = difflib.get_close_matches(norm(t), [norm(w) for w in windows], n=1, cutoff=0.6)
            misses.append(f"HTML: “{t[:110]}”" + (f"\n      Figma closest: “{best[0][:110]}”" if best else "  (no close match in Figma)"))
    html_sq = squash(" ".join(t for _, t in blocks))
    missing = [l for l in pdf_lines if len(squash(l)) > 12 and squash(l) not in html_sq][:25]
    d = misses[:40] + [f"In Figma, not found in HTML (may be design annotations): “{l[:100]}”" for l in missing]
    add("figma_copy", "Copy vs Figma (text diff)", "WARN" if d else "PASS", d, [7], ["Coded copy matches the asset"])


def check_legal(blocks, raw, expected):
    d, flags = [], []
    cps = re.findall(r"©\s*(\d{4})\s*([^.<\n]{3,60})", BeautifulSoup(raw, "html.parser").get_text(" "))
    if not cps:
        flags.append("No © line found")
    for y, who in cps:
        d.append(f"Copyright: © {y} {who.strip()}")
        bu = expected.get("business_unit")
        if bu and squash(bu) not in squash(who):
            flags.append(f"Copyright business name “{who.strip()}” ≠ expected business unit “{bu}”")
    for el, t in blocks:
        m = re.match(r"^(\d{1,2})(\s*)(\S)", t)
        if m and len(t) > 40:
            first = el.find(string=True)
            sup = first is not None and first.find_parent("sup") is not None and first.strip().startswith(m.group(1))
            if sup:
                flags.append(f"Disclaimer {m.group(1)} starts with a superscript number (should be full-size): “{t[:50]}”")
            if m.group(2) != " ":
                flags.append(f"Disclaimer {m.group(1)} needs exactly one space after the number: “{t[:50]}”")
    for snippet in expected.get("legal_required", []):
        if squash(snippet) not in squash(raw):
            flags.append(f"Required legal copy not found: “{snippet[:80]}”")
    d.append("Business-unit legal (columns J/K/L of the accuracy chart) — confirm against the chart")
    add("legal", "Legal & copyright", "FLAG" if flags else "MANUAL", flags + d, [8],
        ["Numbered disclaimers", "Closing sentence business name", "Required legal present"])


def check_header_footer(links, soup, expected):
    head = links[:4]
    ctas = [l["text"] for l in head if re.search(r"my account|join aaa", l["text"] or "", re.I)]
    d = [f"Header links: " + "; ".join(f"{l['text'][:25]} → {(l['resolved'] or '')[:60]}" for l in head[:5])]
    status = "MANUAL"
    if not ctas:
        status = "WARN"; d.append("Neither “My Account” nor “Join AAA” found in the first links")
    elif expected.get("header_cta") and norm(expected["header_cta"]) not in [norm(c) for c in ctas]:
        status = "FLAG"; d.append(f"Header CTA is {ctas} but Jira says {expected['header_cta']}")
    else:
        d.append(f"Header CTA: {ctas[0]}")
    foot = [l for l in links if l["legal_region"]]
    for l in foot:
        if not l["image"] and not l["underlined"]:
            status = "FLAG"; d.append(f"Footer legal link not underlined: {l['text'][:40]}")
    d.append("Header/footer URLs & alt text vs accuracy chart — compare the inventory in qa_results.json against the chart")
    add("header_footer", "Header & footer", status, d, [7], ["Standard header present", "Header copy is either", "LOB footer present",
                                                             "Blue footer logo", "Footer legal links underlined"])


def check_tracking(raw):
    d, status = [], "PASS"
    pix = re.search(r"inboxmonster|inbox-monster|imtrk|@MessageType", raw, re.I)
    if not pix:
        status = "FLAG"; d.append("Inbox Monster tracking pixel / @MessageType not found")
    mt = re.search(r"SET\s+@MessageType\s*=\s*['\"]([^'\"]*)['\"]", raw, re.I)
    if pix and (not mt or mt.group(1) not in ("Marketing", "Transactional")):
        status = "FLAG"; d.append(f"@MessageType should be Marketing or Transactional (found {mt.group(1) if mt else 'unset'!r})")
    for v in ("SegmentName", "SegmentGeneral"):
        m = re.search(rf"SET\s+@{v}\s*=\s*['\"]([^'\"]*)['\"]", raw, re.I)
        d.append(f"@{v}: {m.group(1)!r}" if m else f"@{v}: not set (required for journey sends)")
        if not m and status == "PASS":
            status = "WARN"
    b, e = len(re.findall(r"BeginImpressionRegion", raw, re.I)), len(re.findall(r"EndImpressionRegion", raw, re.I))
    names = re.findall(r"BeginImpressionRegion\s*\(\s*['\"]([^'\"]+)", raw, re.I)
    d.append(f"Impression regions: {b} begin / {e} end — {', '.join(names) or 'none'}")
    if b != e:
        status = "FLAG"; d.append("Begin/End impression region count mismatch")
    add("tracking", "Tracking pixel & impression regions", status, d, [], ["Inbox Monster tracking pixel", "Impression Region code"])


def css_text(soup):
    return "\n".join(s.get_text() for s in soup.find_all("style"))


def check_fonts(soup, raw):
    css = css_text(soup) + "\n" + "\n".join(t.get("style", "") for t in soup.find_all(style=True))
    fams = set(m.strip() for m in re.findall(r"font-family\s*:\s*([^;}\"]+)", css, re.I))
    smart = [f for f in fams if "smart" in f.lower()]
    flags, d = [], [f"font-family stacks: {len(fams)} distinct; with Smart font: {len(smart)}"]
    for f in smart:
        if "arial" not in f.lower():
            flags.append(f"Smart font stack without Arial fallback: {f[:80]}")
    weights = re.findall(r"font-weight\s*:\s*(\w+)", css, re.I)
    if "500" in weights:
        flags.append(f"font-weight:500 used {weights.count('500')}× — team rule: code Figma 500 as 600")
    if "400" in weights:
        flags.append(f"font-weight:400 used {weights.count('400')}× — team rule: code 400 as normal")
    wset = sorted(set(weights))
    d.append(f"Weights used: {', '.join(wset)}")
    if "300" in wset and ("normal" in wset or "400" in wset):
        d.append("Light (300) and Regular both used — both fall back to Arial Regular; emphasis lost in Outlook unless designer OK'd")
    if not smart:
        status = "NA"; d.append("No Smart font found")
    else:
        has_face = bool(re.search(r"@font-face|fonts\.googleapis|\.woff2?", raw, re.I))
        d.append(f"Web font loaded (@font-face/woff/link): {'yes' if has_face else 'NO'}")
        if not has_face:
            flags.append("Smart font referenced but no @font-face/woff found")
        d.append("Rendering of web font weights (Apple Mail desktop + iOS) needs Inbox Monster screenshots")
        status = "FLAG" if flags else "MANUAL"
    add("fonts", "Smart font application", status, flags + d, [15],
        ["Smart web font weights", "Arial fallback preserves bold"])


def check_dark(soup, raw, img_inv):
    css = css_text(soup)
    d = [f"meta color-scheme: {'yes' if soup.find('meta', attrs={'name': 'color-scheme'}) else 'NO'}",
         f"meta supported-color-schemes: {'yes' if soup.find('meta', attrs={'name': 'supported-color-schemes'}) else 'NO'}",
         f"@media (prefers-color-scheme: dark): {'yes' if 'prefers-color-scheme' in css else 'NO'}",
         f"Outlook.com [data-ogsc]/[data-ogsb] rules: {'yes' if 'data-ogs' in css else 'NO'}"]
    # header/footer are shared modules whose dark-mode rendering is expected and accepted — body content only
    cands = [r for r in img_inv if r.get("transparent") and not r.get("white_art") and r.get("region", "body") == "body"]
    for r in cands:
        d.append(f"Transparent non-white PNG (needs light background fill/outline unless inside a button): {r['src'].rsplit('/', 1)[-1][:60]}")
    d.append("Header/footer excluded from dark-mode review (shared modules; their dark rendering is expected)")
    d.append("Gmail app & Outlook force-invert colors; actual dark appearance needs Inbox Monster dark screenshots")
    add("dark_mode", "Dark mode", "WARN" if cands else "MANUAL", d, [14], ["Dark mode: icons have a light-mode-color"])


def check_responsive(soup, img_inv):
    css = css_text(soup)
    mqs = re.findall(r"@media[^{]+", css)
    defined = set(re.findall(r"\.([A-Za-z_][\w-]*)", css))
    used = {c for el in soup.find_all(class_=True) for c in el.get("class", [])}
    resp = {c for c in used if re.search(r"mob|desk|hide|show|stack|full|^m-|^d-|resp|fluid", c, re.I)}
    undefined = sorted(resp - defined)
    d = [f"Media queries: {len(mqs)} — " + "; ".join(m.strip()[:60] for m in mqs[:6])]
    if undefined:
        d.append(f"Responsive-looking classes used but not defined in CSS (typo?): {', '.join(undefined)}")
    mob = [r for r in img_inv if r["hidden_ancestor"]]
    d.append(f"Images hidden on desktop (mobile-specific / show-hide): {len(mob)}")
    for r in mob:
        d.append(f"  mobile/hidden img: {r['src'].rsplit('/', 1)[-1][:60]} alt “{(r['alt'] or '')[:30]}”")
    d.append("Responsive layout vs Figma mobile frame: see renders (if Playwright installed) and Inbox Monster mobile screenshots")
    add("responsive", "Responsive & mobile-specific images", "WARN" if undefined else "MANUAL", d, [13, 16],
        ["Items coded separately for desktop/mobile"])


def check_emoji(subject, preheader_text, blocks):
    hits = []
    for where, t in [("subject", subject or ""), ("preheader", preheader_text or "")] + [("body", t) for _, t in blocks]:
        for m in re.finditer(EMOJI.pattern + "+", t):
            s = m.group(0)
            cps = " ".join(f"U+{ord(c):04X}" for c in s)
            note = []
            if "‍" in s: note.append("ZWJ sequence — may split into multiple glyphs on older Android/Outlook")
            if re.search("[\U0001F1E6-\U0001F1FF]", s): note.append("flag emoji — shows as letters on Windows")
            if len(s) == 1 and ord(s) < 0x2C00 and "️" not in s: note.append("text-default char without U+FE0F — may render monochrome")
            hits.append(f"{where}: {s} ({cps}) {'; '.join(note)}")
    add("emoji", "Emoji", "MANUAL" if hits else "NA",
        hits + (["Check rendering in Inbox Monster: Outlook desktop (Segoe, monochrome), Gmail web (image swap), Android"] if hits else []), [17])


def check_size(raw, eml_html, img_inv):
    b = len(raw.encode("utf-8"))
    d = [f"Build HTML: {b/1024:.1f} KB (SFMC adds tracking/wrappers on send)"]
    status = "PASS"
    if eml_html:
        e = len(eml_html.encode("utf-8"))
        d.append(f"Post-send HTML (from .eml): {e/1024:.1f} KB")
        if e > 102 * 1024:
            status = "FLAG"; d.append("Over 102 KB — Gmail will clip")
    elif b > 90 * 1024:
        status = "WARN"; d.append("Build HTML over 90 KB — likely to clip after SFMC adds tracking; verify with a test send")
    imgkb = sum(r.get("kb", 0) for r in img_inv)
    total = b / 1024 + imgkb
    d.append(f"HTML + images ≈ {total:.0f} KB (limit 600 KB)" + ("" if imgkb else " — images not measured (offline?)"))
    if total > 600:
        status = "FLAG"
    add("size", "Message size & Gmail clipping", status, d, [], ["Total message size", "Gmail clipping"])


def check_basics(soup, raw):
    d, flags = [], []
    if not raw.lstrip().lower().startswith("<!doctype"):
        flags.append("No doctype")
    if not soup.find("meta", attrs={"name": "viewport"}):
        flags.append("No viewport meta")
    if not soup.find("meta", charset=True) and not soup.find("meta", attrs={"http-equiv": re.compile("content-type", re.I)}):
        flags.append("No charset meta")
    if not soup.find("html", lang=True):
        d.append("<html> has no lang attribute (accessibility)")
    if "x-apple-data-detectors" not in raw:
        d.append("No a[x-apple-data-detectors] rule — iOS may create blue links on dates/addresses")
    if not re.search(r"u\s*\+\s*#body|u\s*\+\s*\.body", raw):
        d.append("No Gmail 'u + #body a' rule — Gmail may color auto-detected links blue")
    add("basics", "Document basics & mobile blue-link prevention", "FLAG" if flags else "PASS" if not d else "WARN",
        flags + d, [], ["No mobile blue links"])


EXC_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "validator_exceptions.json")


def prep_for_validator(raw):
    """Neutralise AmpScript so the validator only reports real HTML/CSS problems. Line numbers are preserved."""
    raw = AMP_BLOCK.sub(lambda m: "\n" * m.group(0).count("\n"), raw)
    raw = AMP_INLINE.sub("AMPSCRIPT", raw)
    return re.sub(r"%%[A-Za-z_][\w]*%%", "AMPSCRIPT", raw)


def nu_validate(html):
    r = requests.post("https://validator.w3.org/nu/?out=json", data=html.encode("utf-8"),
                      headers={**UA, "Content-Type": "text/html; charset=utf-8"}, timeout=60)
    r.raise_for_status()
    return r.json().get("messages", [])


def check_validation(paths, enabled):
    rows = ["HTML + CSS validators"]
    if not enabled:
        add("validation", "HTML + CSS validation (Nu HTML Checker)", "MANUAL",
            ["Not run (--offline / --no-validate). Paste each version into validator.w3.org/nu."], [], rows)
        return
    try:
        exc = json.load(open(EXC_FILE, encoding="utf-8"))
    except FileNotFoundError:
        exc = {"patterns": []}
    pats = [(re.compile(e["pattern"]), e["why"]) for e in exc.get("patterns", [])]
    imp_pats = [(re.compile(e["pattern"]), e.get("why", "")) for e in exc.get("important_warnings", [])]
    flags, d, warn_lines, any_ok = [], [], [], False
    for path in paths:
        name = os.path.basename(path)
        try:
            msgs = nu_validate(prep_for_validator(open(path, encoding="utf-8", errors="ignore").read()))
        except Exception as e:
            d.append(f"{name}: validator call failed ({str(e)[:100]}) — validate manually at validator.w3.org/nu")
            continue
        any_ok = True
        errs = [m for m in msgs if m.get("type") == "error"]
        warns = [m for m in msgs if m.get("type") == "info" and m.get("subType") == "warning"]
        # Warnings are ignored (email conventions produce lots of them) except the few listed as important.
        important = [m for m in warns if any(rx.search(m.get("message", "")) for rx, _ in imp_pats)]
        for m in important:
            warn_lines.append(f"{name} L{m.get('lastLine')} (important warning): {m.get('message')[:150]}")
        known, real = {}, []
        for m in errs:
            why = next((w for rx, w in pats if rx.search(m.get("message", ""))), None)
            if why:
                known[why] = known.get(why, 0) + 1
            else:
                real.append(m)
        css_real = sum(1 for m in real if m["message"].startswith("CSS:"))
        d.append(f"{name}: {len(errs)} errors → {len(real)} to fix ({css_real} CSS, {len(real) - css_real} HTML), "
                 f"{len(errs) - len(real)} known email exceptions; {len(warns) - len(important)} routine warnings ignored")
        for why, n in sorted(known.items(), key=lambda x: -x[1]):
            d.append(f"    known exception ×{n}: {why}")
        for m in real[:25]:
            flags.append(f"{name} L{m.get('lastLine')}: {m.get('message')[:150]}")
        if len(real) > 25:
            flags.append(f"{name}: … {len(real) - 25} more in qa_results.json")
        RESULTS_EXTRA.setdefault("validator", {})[name] = real
    status = "FLAG" if flags else ("WARN" if warn_lines else ("PASS" if any_ok else "MANUAL"))
    add("validation", "HTML + CSS validation (Nu HTML Checker, includes CSS)", status, flags + warn_lines + d, [], rows)

# Data Spec + segment names. A Standard build's HTML Email Block only pulls in
# ProjectAmpscript via CONTENTBLOCKBYKEY, so read that file from the project
# folder; Standalone / Via builds SET everything inline. A tiny IF/ELSEIF/ELSE
# walker works out which branch is live, so the scaffold's placeholder SETs in
# the branches that don't apply (A3 Smart Home, Journey) aren't flagged.
SEG_PLACEHOLDER = re.compile(r"^$|EMC_SAMPLE|MMDDYY", re.I)
OLD_SPEC_VARS = ("_CmpgnDataSpecVars_010725", "_CmpgnDataSpecVars_081126")  # pull Segment* from the DE


def amp_effective_vars(code):
    """Walk AmpScript top to bottom and return {@var: value} for the string SETs that are live.
    Only `@Var == 'x'` / `@Var != 'x'` conditions are evaluated; any other condition is
    treated as unknown and its branches are skipped."""
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    vals, stack = {}, []  # stack entries: [parent_live, branch_taken, live]
    tok = re.compile(r"^\s*(?:(ELSEIF|IF|ELSE|ENDIF)\b(.*?)(?=\bTHEN\b|$)|SET\s+(@\w+)\s*=\s*(.+))", re.I)

    def cond(expr):
        m = re.fullmatch(r"\s*(@\w+)\s*(==|!=)\s*['\"]([^'\"]*)['\"]\s*", expr)
        if not m or m.group(1).lower() not in vals:
            return None
        eq = vals[m.group(1).lower()].lower() == m.group(3).lower()
        return eq if m.group(2) == "==" else not eq

    for line in code.splitlines():
        m = tok.match(line)
        if not m:
            continue
        live = all(e[2] for e in stack)
        kw = (m.group(1) or "").upper()
        if kw == "IF":
            c = cond(m.group(2))
            stack.append([live, c is not False and c is not None, live and c is True])
            if c is None:
                stack[-1][1] = True  # unknown: don't let ELSE fire either
        elif kw == "ELSEIF" and stack:
            c = cond(m.group(2))
            parent, taken, _ = stack[-1]
            stack[-1][2] = parent and not taken and c is True
            stack[-1][1] = taken or c is not False
        elif kw == "ELSE" and stack:
            parent, taken, _ = stack[-1]
            stack[-1][2] = parent and not taken
            stack[-1][1] = True
        elif kw == "ENDIF" and stack:
            stack.pop()
        elif m.group(3) and live:
            v = re.match(r"\s*['\"]([^'\"]*)['\"]", m.group(4))
            vals[m.group(3).lower()] = v.group(1) if v else "(expression)"
    return vals


def check_data_spec(html_path, raw, expected):
    d, status = [], "PASS"
    head = "\n".join(AMP_BLOCK.findall(raw))  # @email_version etc. from the HTML Email Block
    src = "build HTML (inline)"
    if re.search(r"CONTENTBLOCKBYKEY\s*\([^)]*_ProjectAmpscript", raw, re.I):
        pa = os.path.join(os.path.dirname(os.path.abspath(html_path)), "ProjectAmpscript.amp")
        if not os.path.isfile(pa):
            add("data_spec", "Data Spec & segment names", "MANUAL",
                ["Build pulls in _ProjectAmpscript but ProjectAmpscript.amp is not next to the HTML — check @DataSpec / @SegmentName / @SegmentGeneral by hand"],
                [6], ["Ampscript inspected"])
            return
        head += "\n" + open(pa, encoding="utf-8", errors="ignore").read()
        src = "ProjectAmpscript.amp"
    v = amp_effective_vars(head)
    et, bu, ds = v.get("@emailtype", ""), v.get("@businessunit", ""), v.get("@dataspec", "")
    sn, sg = v.get("@segmentname"), v.get("@segmentgeneral")
    d.append(f"Read from {src}: @EmailType={et or '—'} · @BusinessUnit={bu or '—'} · @DataSpec={ds or '—'}")
    d.append(f"Live @SegmentName={sn!r} · @SegmentGeneral={sg!r}")

    for name, val in (("@SegmentName", sn), ("@SegmentGeneral", sg)):
        if val is None:
            status = "FLAG"; d.append(f"{name} is never SET in the live branch — Inbox Monster tagging and the test subject line will be blank")
        elif SEG_PLACEHOLDER.search(val):
            what = f"still the scaffold placeholder {val!r}" if val else "empty"
            status = "FLAG"; d.append(f"{name} is {what} — set it to the campaign name")

    camp = expected.get("campaign_name", "")
    if camp and sn and not SEG_PLACEHOLDER.search(sn):
        gen = re.sub(r"_\d{6}$", "", camp)
        if squash(sn) != squash(camp):
            status = "FLAG" if status == "FLAG" else "WARN"; d.append(f"@SegmentName {sn!r} ≠ Jira campaign name {camp!r}")
        if sg and not SEG_PLACEHOLDER.search(sg) and squash(sg) != squash(gen):
            status = "FLAG" if status == "FLAG" else "WARN"; d.append(f"@SegmentGeneral {sg!r} ≠ campaign name without its _MMDDYY ({gen!r})")

    if et.lower() == "campaign" and bu.lower() == "aaa mwg":
        if ds not in ("Engage", "MIF"):
            status = "FLAG"; d.append(f"@DataSpec must be 'Engage' or 'MIF' on an AAA MWG campaign (got {ds!r}) — neither data-mapping branch runs, so @FirstName is never set")
        exp_ds = expected.get("data_spec")
        if exp_ds and ds and exp_ds.lower() != ds.lower():
            status = "FLAG"; d.append(f"@DataSpec is {ds!r} but the Jira ticket says {exp_ds!r} (MIF = ticket mentions Members in Force / MiF)")
        if ds == "Engage":
            old = [o for o in OLD_SPEC_VARS if o.lower() in head.lower()]
            if old:
                status = "FLAG"; d.append(f"Engage branch still calls {', '.join(old)} — that version re-reads Segment Name/General from the DE and overwrites the manual SETs; use _CmpgnDataSpecVars_102826")
    elif ds:
        d.append(f"@DataSpec only applies to AAA MWG campaigns — ignored for {et or '?'} / {bu or '?'}")
    add("data_spec", "Data Spec & segment names", status, d, [6], ["Ampscript inspected"])



# ----------------------------------------------------------------------------- main
def run_check(a):
    raw = open(a.html, encoding="utf-8", errors="ignore").read()
    expected = load_expected(a.expected)
    msg, eml_html = (load_eml(a.eml) if a.eml else (None, None))
    if a.sent_html and not eml_html:  # Inbox Monster "Download the HTML Content"
        eml_html = open(a.sent_html, encoding="utf-8", errors="ignore").read()
    masked = AMP_BLOCK.sub(lambda m: "<!--AMPBLOCK-->", raw)
    soup = BeautifulSoup(masked, "html.parser")
    order = {id(n): i for i, n in enumerate(soup.descendants)}
    legal_pos, legal_how = find_legal_start(soup, order)
    if a.legal_marker:
        hit = soup.find(string=re.compile(re.escape(a.legal_marker)))
        if hit is not None:
            legal_pos, legal_how = order[id(hit)], f"--legal-marker “{a.legal_marker}”"

    regions = find_regions(soup)
    amp_vars = check_ampscript(raw, eml_html)
    subject = check_subject(soup, msg, expected)
    pre = check_preheader(soup, expected)
    links, redirects = check_links(soup, raw, amp_vars, expected, order, a.offline, legal_pos, legal_how, regions)
    if eml_html and os.path.abspath(a.sent_html or "") != os.path.abspath(a.html):  # tracked links as actually sent
        esoup = BeautifulSoup(eml_html, "html.parser")
        eorder = {id(n): i for i, n in enumerate(esoup.descendants)}
        ep, eh = find_legal_start(esoup, eorder)
        n0 = len(RESULTS)
        check_links(esoup, eml_html, {}, expected, eorder, a.offline, ep, eh, find_regions(esoup))
        RESULTS[n0]["id"], RESULTS[n0]["title"] = "links_sent", "URLs as sent (post-send HTML, through SFMC click tracking)"
    hdr, ftr = regions
    RESULTS_EXTRA["regions"] = {"header": "found" if hdr is not None else "not found",
                                "footer": "found" if ftr is not None else "not found"}
    check_phone_text(soup)
    check_unsub(links, msg, expected)
    img_inv = check_images(soup, a.offline, regions)
    blocks = leaf_blocks(soup, skip=pre)
    check_campaign_and_date(links, raw, expected)
    check_ab(raw, expected, a.version or [])
    check_data_spec(a.html, raw, expected)
    check_copy_vs_figma(blocks, a.figma)
    check_legal(blocks, masked, expected)
    check_header_footer(links, soup, expected)
    check_tracking(raw)
    check_fonts(soup, raw)
    check_dark(soup, raw, img_inv)
    check_responsive(soup, img_inv)
    check_emoji(subject, pre.get_text().split("‌")[0].strip() if pre else "", blocks)
    check_size(raw, eml_html, img_inv)
    check_basics(soup, raw)
    check_validation([a.html] + (a.version or []), not (a.offline or a.no_validate))

    for l in links:
        l.pop("_el", None)
    out = {"inputs": {"html": a.html, "eml": a.eml, "expected": a.expected, "figma": a.figma, "offline": a.offline},
           "checks": RESULTS, "links": links, "images": img_inv,
           "redirects": [{k: v for k, v in r.items() if k != "body"} for r in redirects],
           "copy_blocks": [t for _, t in blocks], **RESULTS_EXTRA}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)

    order_ = {"FLAG": 0, "WARN": 1, "MANUAL": 2, "PASS": 3, "NA": 4, "INFO": 5}
    print(f"email_qa: {len(RESULTS)} checks → {a.out}")
    for r in sorted(RESULTS, key=lambda r: order_[r["status"]]):
        print(f"[{r['status']:6}] {r['title']}")
        if r["status"] in ("FLAG", "WARN"):
            for x in r["details"][:12]:
                print(f"         - {x}")
            if len(r["details"]) > 12:
                print(f"         … {len(r['details']) - 12} more in JSON")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--html", required=True, help="build HTML (with AmpScript)")
    c.add_argument("--eml", help="test send saved as .eml (subject, from, tracked links, post-send size)")
    c.add_argument("--sent-html", help="post-send HTML (Inbox Monster 'Download the HTML Content'); used when no .eml")
    c.add_argument("--expected", help="expected.json built from the Jira export")
    c.add_argument("--figma", help="Figma PDF export (text layer used for copy diff)")
    c.add_argument("--version", action="append", help="other version HTML (A/B or segment variants) to diff against")
    c.add_argument("--legal-marker", help="text that marks the start of the legal region")
    c.add_argument("--out", default="qa_results.json")
    c.add_argument("--offline", action="store_true", help="skip HTTP checks (links, redirects, images)")
    c.add_argument("--no-validate", action="store_true",
                   help="don't send the HTML to validator.w3.org (on by default; AmpScript is stripped first)")
    d = sub.add_parser("doc-text")
    d.add_argument("path")
    a = p.parse_args()
    if a.cmd == "doc-text":
        sys.stdout.reconfigure(encoding="utf-8")
        print(doc_text(a.path))
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        run_check(a)


if __name__ == "__main__":
    main()
