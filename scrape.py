#!/usr/bin/env python3
"""Scrape ABMS Conference 2026 sessions, speakers and topics from EventScribe.

Writes raw JSON to data/. Run build_vault.py afterwards to generate the vault.
"""
import json
import os
import re
import sys
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor

BASE = "https://abmsconference2026.eventscribe.net"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(DATA, "cache")

AGENDA = "/agenda.asp?BCFO=&pfp=BrowsebyDay&fa=&fb=&fc=&fd=&all=1"
BUCKETS = "/SearchByBucket.asp?f=TrackName&pfp=BrowsebyBucket"
BIOS = "/biography.asp?pfp=Speakers"


def fetch(path, force=False):
    """GET a path relative to BASE, with an on-disk cache."""
    key = re.sub(r"[^A-Za-z0-9]+", "_", path)[:120] + ".html"
    dest = os.path.join(CACHE, key)
    if os.path.exists(dest) and not force:
        with open(dest, encoding="utf-8") as fh:
            return fh.read()
    # Shell out to curl: this machine's Python trust store rejects the origin's
    # certificate chain, while curl's accepts it.
    for attempt in range(4):
        proc = subprocess.run(
            ["curl", "-sL", "--compressed", "-A", UA, "--max-time", "45", BASE + path],
            capture_output=True,
        )
        if proc.returncode == 0 and proc.stdout:
            body = proc.stdout.decode("utf-8", "replace")
            break
        if attempt == 3:
            raise RuntimeError(f"failed to fetch {path}: {proc.stderr.decode()[:200]}")
        print(f"  retry {attempt + 1} for {path}", file=sys.stderr)
        time.sleep(2 * (attempt + 1))
    os.makedirs(CACHE, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(body)
    time.sleep(0.25)  # be polite to the origin
    return body


def strip_tags(html):
    html = re.sub(r"<(script|style).*?</\1>", "", html, flags=re.S | re.I)
    html = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", html, flags=re.I)
    html = re.sub(r"<[^>]+>", "", html)
    return unescape(html)


def unescape(text):
    import html as _html

    text = _html.unescape(text)
    return text.replace("\xa0", " ")


def clean(text):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", text))).strip()


def clean_multiline(text):
    """Strip tags but keep paragraph breaks."""
    text = unescape(re.sub(r"<[^>]+>", "", text))
    return "\n".join(re.sub(r"[ \t]+", " ", l).strip() for l in text.split("\n"))


# --------------------------------------------------------------------------
# Agenda: day / time / title / presentation id
# --------------------------------------------------------------------------
DAY_RE = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"(\w+)\s+(\d+),\s+(\d{4})"
)
MONTHS = {
    m: i
    for i, m in enumerate(
        "January February March April May June July August September "
        "October November December".split(),
        1,
    )
}


def parse_agenda(html):
    """Return ordered session stubs with the day heading that precedes them."""
    rows = []
    # Split on day headings so each session inherits the correct date.
    marks = [(m.start(), m) for m in DAY_RE.finditer(html)]
    row_re = re.compile(
        r'data-url="ajaxcalls/PresentationInfo\.asp\?PresentationID=(\d+)"'
        r'[^>]*data-buildcode="(\w*)"(.*?)</li>',
        re.S,
    )
    for m in row_re.finditer(html):
        presid, buildcode, body = m.group(1), m.group(2), m.group(3)
        day = None
        for pos, dm in marks:
            if pos < m.start():
                day = dm
            else:
                break
        title_m = re.search(
            r'class="list-row-primary"><span[^>]*>(.*?)</span>', body, re.S
        )
        time_m = re.search(r'class="tipsytip" title="">(.*?)</span>', body, re.S)
        loc_m = re.search(r'class="text-12">\s*Location:\s*(.*?)</div>', body, re.S)
        iso = None
        if day:
            iso = f"{day.group(4)}-{MONTHS[day.group(2)]:02d}-{int(day.group(3)):02d}"
        rows.append(
            {
                "presentation_id": presid,
                "build_code": buildcode,
                "title": clean(title_m.group(1)) if title_m else "",
                "time_raw": clean(time_m.group(1)) if time_m else "",
                "location": clean(loc_m.group(1)) if loc_m else "",
                "date": iso,
                "weekday": day.group(1) if day else None,
                "order": len(rows),
            }
        )
    return rows


# --------------------------------------------------------------------------
# Buckets: topic/track -> presentation ids
# --------------------------------------------------------------------------
def parse_buckets(html):
    """Map each track bucket heading to the presentation ids nested under it."""
    tracks = []
    parts = re.split(r"""<li class=['"]list-group-item list-row bucket['"]""", html)
    for chunk in parts[1:]:
        name_m = re.search(r'class="list-row-primary">(.*?)</div>', chunk, re.S)
        if not name_m:
            continue
        name = clean(name_m.group(1))
        wrap = re.search(r'<div class="bucketwrapper".*?>(.*)', chunk, re.S)
        ids = re.findall(r'data-presid="(\d+)"', wrap.group(1)) if wrap else []
        if name:
            tracks.append({"raw_name": name, "presentation_ids": ids})
    return tracks


# --------------------------------------------------------------------------
# Presentation detail popup
# --------------------------------------------------------------------------
def parse_presentation(presid, html):
    speakers = []
    for m in re.finditer(
        r'<li class="speakerrow" data-presenterid="(\d+)"(.*?)</li>', html, re.S
    ):
        pid, block = m.group(1), m.group(2)
        name_m = re.search(r"speaker-name[^>]*>(.*?)</p>", block, re.S)
        aff_m = re.search(r'prof-text[^>]*>(.*?)</p>', block, re.S)
        # prof-text packs "Role<br/>Organization" into one node.
        role, org = "", ""
        if aff_m:
            bits = [clean(b) for b in re.split(r"<br\s*/?>", aff_m.group(1))]
            bits = [b for b in bits if b]
            if len(bits) == 1:
                org = bits[0]
            elif bits:
                role, org = bits[0], ", ".join(bits[1:])
        speakers.append(
            {
                "presenter_id": pid,
                "name": clean(name_m.group(1)) if name_m else "",
                "role": role,
                "organization": org,
                "affiliation": ", ".join(x for x in (role, org) if x),
            }
        )
    title_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
    desc_m = re.search(
        r'<div class="PresentationAbstractText[^"]*">(.*?)</div>', html, re.S
    )
    desc = ""
    if desc_m:
        raw = re.sub(r"<br\s*/?>|</p>", "\n", desc_m.group(1), flags=re.I)
        desc = re.sub(r"\n{3,}", "\n\n", clean_multiline(raw)).strip()
        desc = re.sub(r"^Description:\s*", "", desc)
    return {
        "presentation_id": presid,
        "detail_title": clean(title_m.group(1)) if title_m else "",
        "speakers": speakers,
        "description": desc,
    }


# --------------------------------------------------------------------------
# Presenter detail popup
# --------------------------------------------------------------------------
def parse_presenter(pid, html):
    name_m = re.search(r'<h[12][^>]*>(.*?)</h[12]>', html, re.S)
    photo_m = re.search(r"(https://www\.conferenceharvester\.com/uploads/[^\"'<> ]+)", html)
    text = strip_tags(html)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # Trim chrome: everything before the presenter's name, and the footer.
    name = clean(name_m.group(1)) if name_m else ""
    if name and name in lines:
        lines = lines[lines.index(name) + 1:]
    for stop in ("Designed by", "Technical Support", "Give Feedback"):
        lines = [l for l in lines if not l.startswith(stop)]
    lines = [l for l in lines if "Copyright" not in l and l not in ("Cadmium", "|")]
    title = lines[0] if lines else ""
    bio = "\n\n".join(lines[1:]).strip()
    return {
        "presenter_id": pid,
        "name": name,
        "title": title,
        "bio": bio,
        "photo": photo_m.group(1) if photo_m else "",
    }


def parse_bio_directory(html):
    """Photos and social handles from the speaker directory listing."""
    out = {}
    for chunk in re.split(r'data-presenterid="', html)[1:]:
        pid = re.match(r"(\d+)", chunk)
        if not pid:
            continue
        photo = re.search(r"data-src='(https://[^']+)'", chunk)
        socials = {}
        for s in re.finditer(r'socialicon-(\w+)[^>]*data-url="([^"]+)"', chunk):
            socials[s.group(1)] = unescape(s.group(2))
        out[pid.group(1)] = {
            "photo": photo.group(1) if photo else "",
            "socials": socials,
        }
    return out


def main():
    os.makedirs(DATA, exist_ok=True)
    force = "--refresh" in sys.argv

    print("Fetching agenda ...")
    sessions = parse_agenda(fetch(AGENDA, force))
    print(f"  {len(sessions)} agenda rows")

    print("Fetching topic buckets ...")
    tracks = parse_buckets(fetch(BUCKETS, force))
    print(f"  {len(tracks)} raw buckets")

    print("Fetching speaker directory ...")
    directory = parse_bio_directory(fetch(BIOS, force))
    print(f"  {len(directory)} directory entries")

    print(f"Fetching {len(sessions)} presentation detail pages ...")
    with ThreadPoolExecutor(max_workers=4) as pool:
        details = list(
            pool.map(
                lambda s: parse_presentation(
                    s["presentation_id"],
                    fetch(
                        f"/fsPopup.asp?PresentationID={s['presentation_id']}&mode=presInfo",
                        force,
                    ),
                ),
                sessions,
            )
        )
    by_pres = {d["presentation_id"]: d for d in details}
    for s in sessions:
        s.update(by_pres.get(s["presentation_id"], {}))

    # Every speaker who actually appears on the programme, plus anyone listed in
    # the directory but not attached to a session.
    pids = sorted(
        {sp["presenter_id"] for s in sessions for sp in s.get("speakers", [])}
        | set(directory)
    )
    print(f"Fetching {len(pids)} presenter detail pages ...")
    with ThreadPoolExecutor(max_workers=4) as pool:
        people = list(
            pool.map(
                lambda p: parse_presenter(
                    p,
                    fetch(f"/ajaxcalls/presenterInfo.asp?PresenterId={p}", force),
                ),
                pids,
            )
        )

    speakers = {}
    for p in people:
        key = p["presenter_id"]
        rec = speakers.setdefault(
            key,
            {
                "presenter_id": p["presenter_id"],
                "name": p["name"],
                "title": p["title"],
                "bio": p["bio"],
                "photo": p["photo"],
                "socials": {},
            },
        )
        if len(p["bio"]) > len(rec["bio"]):
            rec["bio"] = p["bio"]
        if not rec["photo"]:
            rec["photo"] = p["photo"]
        extra = directory.get(p["presenter_id"] or "", {})
        if extra.get("photo") and not rec["photo"]:
            rec["photo"] = extra["photo"]
        rec["socials"].update(extra.get("socials", {}))

    out = {
        "sessions": sessions,
        "tracks": tracks,
        "speakers": list(speakers.values()),
    }
    with open(os.path.join(DATA, "abms2026.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print(
        f"\nWrote data/abms2026.json: {len(sessions)} sessions, "
        f"{len(speakers)} unique speakers, {len(tracks)} buckets"
    )


if __name__ == "__main__":
    main()
