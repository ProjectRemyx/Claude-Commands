"""Parse an AAA MWG Email Intake Form .doc into structured JSON.

Usage:
    py .claude/scripts/parse_intake.py <path-to-intake.doc>

The intake now arrives as a Jira ticket export (Microsoft Word .doc).
The actual intake fields live in the ticket "Description" body as one
field per line in the form ``Label: value``. Jira metadata (Status,
Reporter, Issue links, ...) and the trailing Comments are ignored
because their labels are not in LABEL_MAP.

Reading the binary .doc requires Word COM automation (pywin32) -- the
same mechanism de_tabs.py uses for the data-extension .xls. Emits JSON
on stdout that /new-project consumes. Best-guess mappings to
ProjectAmpscript variable values are included but Claude is expected to
confirm them with the user before writing files.
"""
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from win32com.client import dynamic


# Intake-form label (normalized: lower-case, straight apostrophe) -> raw key.
# Anything not in this table (Jira metadata, comments, section headers,
# QA / Reporting / Campaign URLs lines) is ignored.
LABEL_MAP = {
    "requestor name/email": "requestor",
    "requestor lob": "lob_product",
    "objective": "objective_purpose",
    "campaign name a": "campaign_name_a",
    "campaign name b": "campaign_name_b",
    "campaign topic": "campaign_topic",
    "project approvers": "approvers",
    "kpi's to track": "kpis",
    "single most important takeaway": "smit",
    "channel": "channel",
    "project execution type": "execution_type",
    "request type": "request_type",
    "personalization description": "personalization",
    "a/b test": "ab_test",
    "a/b test goal & description": "ab_goal",
    "request send date": "send_date",
    "request send time": "send_time",
    "request send time zone": "send_tz",
    "unsubscribe link": "unsubscribe_lob",
    "target audience description": "audience_desc",
    "deployment system": "deploy_system",
    "copy brief link": "copy_brief",
    "figma design link": "figma_link",
    "lucid chart link": "lucid_link",
    "pdf links": "pdf_links",
    "other links": "other_links",
    "test recipients": "test_recipients",
    "seed list": "seed_list",
    "additional seed list selections": "additional_seeds",
    "disclaimer information for footer": "additional_legal",
    "additional useful information": "additional_info",
}

# Subject Line / Preview Text appear twice (an A block then a B block).
# They are resolved positionally rather than via LABEL_MAP.
DUP_LABELS = {"subject line", "preview text"}

# Full set of raw keys the JSON contract guarantees (same shape as the
# old .xlsx parser so /new-project downstream is unchanged).
ALL_KEYS = sorted(set(LABEL_MAP.values()) | {
    "subject_line_a", "preview_text_a", "subject_line_b", "preview_text_b",
})


# LOB/Product (intake) -> @LOBHeader value (ProjectAmpscript)
LOB_HEADER_MAP = {
    "auto buying": "Auto Buying",
    "auto glass": "Auto Glass",
    "auto repair": "Auto Repair",
    "credit card": "Credit Card",
    "discounts": "Discounts",
    "insurance": "Insurance",
    "membership": "Membership",
    "aaa smart home security": "AAA Smart Home Security",
    "aaa smart business security": "AAA Smart Business Security",
    "travel": "Travel",
}

# LOB/Product (intake) -> @LOBFooter (ProjectAmpscript) best-guess
LOB_FOOTER_MAP = {
    "auto buying": "AAA.com/AutoBuying",
    "auto glass": "AAA.com/AutoGlass",
    "auto repair": "AAA.com/AutoRepair",
    "credit card": "AAA.com/Gift",
    "discounts": "Discounts",
    "insurance": "AAA.com/Insurance",
    "membership": "AAA.com/Membership",
    "travel": "AAA.com/Travel",
    "aaa smart home security": "AAA.com/Smart",
    "aaa smart business security": "AAA.com/SmartBusiness",
}

# Unsubscribe link (intake) is usually already a valid @LOBunsubscribe.
# Provide a lower-case alias table for confidence.
LOB_UNSUB_VALUES = {
    "default", "highlights", "visa credit card",
    "auto and other vehicle insurance", "auto repair",
    "cyber newsletter", "emergency and safety",
    "home and other property insurance", "identity protection",
    "life insurance", "discounts and benefits",
    "membership newsletter", "new offers and innovations",
    "smart home", "travel", "evia",
}

# Subject/Preview values on journey intakes are prefixed "Email 1: ", etc.
EMAIL_PREFIX_RE = re.compile(r"^\s*Email\s*\d+\s*:\s*", re.IGNORECASE)

# Values that mean "no real legal copy was provided" -- treated as empty
# additional_legal so /new-project does not append them to ProjectLegal.htm.
NON_LEGAL_VALUES = {
    "", "n/a", "na", "none", "see figma", "see the figma",
    "see creative", "see copy", "tbd",
}


def norm_label(s: str) -> str:
    """Normalize a label for matching: lower-case, straight apostrophe."""
    return s.strip().lower().replace("’", "'")


def read_doc_lines(path: Path) -> list:
    """Open a .doc via Word COM and return its text as a list of
    non-empty, trimmed lines (tables and paragraphs in document order).

    Two robustness measures:
    * dynamic.Dispatch forces late binding so a corrupted pywin32 gen_py
      cache can't break the launch.
    * We open a temp copy. shutil.copy does not carry NTFS alternate data
      streams, so the copy loses any Mark-of-the-Web (Zone.Identifier) the
      downloaded .doc had -- otherwise Word opens it in Protected View and
      refuses COM access."""
    tmp_dir = tempfile.mkdtemp(prefix="intake_")
    tmp_doc = os.path.join(tmp_dir, "intake" + path.suffix)
    shutil.copy(str(path), tmp_doc)

    word = dynamic.Dispatch("Word.Application")
    word.Visible = False
    try:
        word.DisplayAlerts = 0  # wdAlertsNone
    except Exception:
        pass
    doc = None
    try:
        doc = word.Documents.Open(
            FileName=tmp_doc,
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
        )
        text = doc.Content.Text or ""
    finally:
        if doc is not None:
            doc.Close(False)
        word.Quit()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Word uses \r for paragraph marks, \x07 for table cell/row ends,
    # \x0b for manual line breaks, \x0c for page breaks.
    for ch in ("\x07", "\x0b", "\x0c", "\r"):
        text = text.replace(ch, "\n")
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def parse_records(lines: list) -> dict:
    """Walk lines, split each on the first ':', and pull intake fields."""
    raw = {k: "" for k in ALL_KEYS}
    subjects, previews = [], []

    for line in lines:
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        nl = norm_label(left)
        val = right.strip()
        if nl in DUP_LABELS:
            (subjects if nl == "subject line" else previews).append(val)
        elif nl in LABEL_MAP and not raw[LABEL_MAP[nl]]:
            raw[LABEL_MAP[nl]] = val

    raw["subject_line_a"] = subjects[0] if len(subjects) > 0 else ""
    raw["subject_line_b"] = subjects[1] if len(subjects) > 1 else ""
    raw["preview_text_a"] = previews[0] if len(previews) > 0 else ""
    raw["preview_text_b"] = previews[1] if len(previews) > 1 else ""
    return raw


def derive_mmddyy(campaign_name: str, send_date: str) -> str:
    """Project date is the trailing _MMDDYY in the campaign name."""
    m = re.search(r"_(\d{6})$", campaign_name)
    if m:
        return m.group(1)
    # Fallback: derive from send_date (intake gives MM/DD/YYYY).
    if send_date:
        token = send_date.split()[0]
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
            try:
                return datetime.strptime(token, fmt).strftime("%m%d%y")
            except ValueError:
                continue
    return ""


def derive_year(mmddyy: str) -> str:
    if not mmddyy or len(mmddyy) != 6:
        return ""
    yy = int(mmddyy[4:6])
    # YY < 80 -> 20YY, else 19YY (we won't see 19xx in practice)
    return f"20{yy:02d}" if yy < 80 else f"19{yy:02d}"


def _lob_lookup(lob: str, table: dict, default: str) -> str:
    """Exact match first, then longest-key contains-match (handles
    'Discounts & Rewards' -> 'discounts')."""
    s = lob.strip().lower()
    if s in table:
        return table[s]
    for key in sorted(table, key=len, reverse=True):
        if key in s:
            return table[key]
    return default


def map_lob_header(lob: str) -> str:
    if not lob:
        return "No LOB Header"
    return _lob_lookup(lob, LOB_HEADER_MAP, "")


def map_lob_footer(lob: str) -> str:
    if not lob:
        return "AAA.com"
    return _lob_lookup(lob, LOB_FOOTER_MAP, "AAA.com")


def map_email_type(execution_type: str) -> str:
    """Project Execution Type -> @EmailType (Campaign | Journey | Triggered)."""
    if not execution_type:
        return ""
    t = execution_type.lower()
    # Order matters: "Triggered" wins over "Journey" if both are present,
    # since journeys-omnichannel-triggered emails behave as triggered sends.
    if "triggered" in t:
        return "Triggered"
    if "journey" in t:
        return "Journey"
    if "campaign" in t:
        return "Campaign"
    return ""


def map_message_type(objective: str, execution_type: str) -> str:
    """Best-guess @MessageType. Most marketing sends are 'Marketing'.
    Confirmation by the user is expected."""
    blob = f"{objective} {execution_type}".lower()
    if "transactional" in blob:
        return "Transactional"
    return "Marketing"


def map_business_unit(deploy_system: str) -> str:
    if not deploy_system:
        return ""
    s = deploy_system.strip().lower()
    if "a3" in s:
        return "A3 Smart Home"
    if "aaa mwg" in s or "mwg" in s:
        return "AAA MWG"
    return deploy_system.strip()


def map_unsub_lob(unsub: str) -> str:
    if not unsub:
        return "Default"
    return unsub.strip()


def strip_email_prefix(text: str) -> str:
    """Drop a leading 'Email N:' prefix from journey subject/preview copy."""
    return EMAIL_PREFIX_RE.sub("", text).strip()


def clean_legal(text: str) -> str:
    """Empty out placeholder disclaimers ('see figma', 'N/A', ...)."""
    return "" if text.strip().lower() in NON_LEGAL_VALUES else text.strip()


CAMPAIGN_URL_HEADERS = {
    "url placement",
    "type of clickable asset",
    "cell instructions",
    "final web url",
}


def parse_campaign_urls(lines: list) -> list:
    """Pull the "Campaign URLs" table out of the ticket Description.

    In the .doc it is a 4-column table (URL Placement | Type of Clickable
    Asset | Cell Instructions | Final Web URL). read_doc_lines() has already
    flattened Word's \\x07 cell marks to newlines and dropped empty cells, so
    the table arrives as a flat run of lines. Anchor on the URL: the three
    lines before it are its placement, asset type, and cell instructions.

    Returns [{placement, section, type, cell_instructions, url}, ...] in
    document order. `section` is the integer from a "(section N)" prefix when
    the designer numbered the placement, else None -- that number matches the
    section order in the creative, so it maps a URL straight to a module."""
    try:
        start = next(i for i, ln in enumerate(lines)
                     if ln.strip().lower() == "campaign urls")
    except StopIteration:
        return []

    rows = []
    for i, ln in enumerate(lines[start:], start):
        if not ln.lower().startswith("http"):
            continue
        # Grab up to 4 preceding cells: a "(section N)" marker often sits on
        # its own line because the placement cell has a paragraph break in it.
        prev = []
        j = i - 1
        while j >= start and len(prev) < 4:
            cand = lines[j].strip()
            low = cand.lower()
            # Stop at the header row or a preceding URL; don't run past them.
            if low in CAMPAIGN_URL_HEADERS or low.startswith("http"):
                break
            prev.insert(0, cand)
            j -= 1

        section = None
        sec_only = re.compile(r"^\(\s*section\s*(\d+)\s*\)$", re.I)
        if len(prev) == 4:
            m0 = sec_only.match(prev[0])
            if m0:
                section = int(m0.group(1))
                prev = prev[1:]
            else:
                prev = prev[1:]  # extra cell we can't attribute; drop the oldest
        while len(prev) < 3:
            prev.insert(0, "")
        placement, kind, instructions = prev[:3]
        # The marker can also be inline: "(section 2)DMV Services".
        m = re.match(r"\(\s*section\s*(\d+)\s*\)\s*(.*)", placement, re.I)
        if m:
            section = int(m.group(1))
        rows.append({
            "placement": (m.group(2).strip() if m else placement).strip(),
            "section": section,
            "type": kind,
            "cell_instructions": instructions,
            "url": ln.strip(),
        })
    return rows


def parse(path: Path) -> dict:
    lines = read_doc_lines(path)
    raw = parse_records(lines)

    campaign = raw["campaign_name_a"]
    mmddyy = derive_mmddyy(campaign, raw["send_date"])
    year = derive_year(mmddyy)
    lob = raw["lob_product"]

    return {
        "intake_file": str(path),
        "raw": raw,
        "derived": {
            "campaign_name": campaign,
            "mmddyy": mmddyy,
            "year": year,
        },
        "ampscript_proposed": {
            "BusinessUnit": map_business_unit(raw["deploy_system"]),
            "MessageType": map_message_type(
                raw["objective_purpose"], raw["execution_type"]
            ),
            "EmailType": map_email_type(raw["execution_type"]),
            "LOBHeader": map_lob_header(lob),
            "LOBFooter": map_lob_footer(lob),
            "LOBunsubscribe": map_unsub_lob(raw["unsubscribe_lob"]),
            "ABVersion": "" if raw["ab_test"].strip().lower() in ("no", "") else "A",
            "SubjectLine": strip_email_prefix(raw["subject_line_a"]),
            "PreviewText": strip_email_prefix(raw["preview_text_a"]),
            "SegmentName": campaign,
            "SegmentGeneral": "_".join(campaign.split("_")[:-1]) if "_" in campaign else campaign,
        },
        "extras": {
            "figma_link": raw["figma_link"],
            "copy_brief": raw["copy_brief"],
            "additional_legal": clean_legal(raw["additional_legal"]),
            "additional_info": raw["additional_info"],
            "send_date": raw["send_date"],
        },
        "campaign_urls": parse_campaign_urls(lines),
    }


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"ERROR: {path} does not exist", file=sys.stderr)
        sys.exit(1)
    out = parse(path.resolve())
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
