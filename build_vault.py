#!/usr/bin/env python3
"""Generate an Obsidian vault from data/abms2026.json.

Every note carries YAML frontmatter for Dataview and links out to every related
note, so the graph is fully connected in both directions.
"""
import json
import os
import re
import shutil
from collections import defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "abms2026.json")
VAULT = os.path.join(HERE, "ABMS 2026")

CONF = "ABMS Conference 2026"
EVENTSCRIBE = "https://abmsconference2026.eventscribe.net"

# Source data has typos that split single tracks into several buckets.
TRACK_ALIASES = {
    "Artificial Intelligence (Al): Optimizing Learning and Improvement in "
    "Certification Programs and Health Care Delivery Systems":
        "Artificial Intelligence (AI): Optimizing Learning and Improvement in "
        "Certification Programs and Health Care Delivery Systems",
    "Board Certfication and Professionalism": "Board Certification and Professionalism",
    "Emerging Landscape of the Physician Work Force":
        "The Emerging Landscape of the Physician Workforce",
    "Programs/The Emerging Landscape of the Physician Workforce":
        "The Emerging Landscape of the Physician Workforce",
}

# Short, filename-friendly names for the long official track titles.
TRACK_SHORT = {
    "Artificial Intelligence (AI): Optimizing Learning and Improvement in "
    "Certification Programs and Health Care Delivery Systems":
        "Artificial Intelligence",
    "Board Certification and Professionalism": "Board Certification and Professionalism",
    "Emerging Topics for the Certification Community": "Emerging Topics",
    "Research and Innovations: Informing the Future of Certification Programs":
        "Research and Innovations",
    "The Emerging Landscape of the Physician Workforce": "Physician Workforce",
}


def safe(name):
    """Make a string usable as an Obsidian filename."""
    name = re.sub(r'[\\/:*?"<>|#^\[\]]', "-", name)
    name = re.sub(r"\s+", " ", name).strip(" .-")
    return name[:100].strip()


def yaml_str(v):
    v = str(v).replace('"', "'")
    return f'"{v}"'


def yaml_list(items):
    if not items:
        return " []"
    return "\n" + "\n".join(f"  - {yaml_str(i)}" for i in items)


def fm(pairs):
    """Render a YAML frontmatter block from an ordered list of (key, value)."""
    out = ["---"]
    for k, v in pairs:
        if isinstance(v, list):
            out.append(f"{k}:{yaml_list(v)}")
        elif isinstance(v, bool):
            out.append(f"{k}: {str(v).lower()}")
        elif isinstance(v, int):
            out.append(f"{k}: {v}")  # unquoted so Dataview can sort numerically
        elif v is None or v == "":
            out.append(f"{k}: ")
        else:
            out.append(f"{k}: {yaml_str(v)}")
    out.append("---")
    return "\n".join(out)


def parse_time(raw):
    """'8:45 AM - 10:45 AM CST' -> ('08:45', '10:45')."""
    m = re.match(r"(\d+:\d+\s*[AP]M)\s*-\s*(\d+:\d+\s*[AP]M)", raw or "", re.I)
    if not m:
        return "", ""
    def to24(t):
        return datetime.strptime(re.sub(r"\s+", " ", t.strip().upper()), "%I:%M %p").strftime("%H:%M")
    return to24(m.group(1)), to24(m.group(2))


def write(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body.rstrip() + "\n")


def main():
    with open(DATA, encoding="utf-8") as fh:
        d = json.load(fh)
    sessions, tracks, speakers = d["sessions"], d["tracks"], d["speakers"]

    if os.path.exists(VAULT):
        shutil.rmtree(VAULT)

    # ---- normalise tracks ------------------------------------------------
    pres_tracks = defaultdict(set)
    canon_variants = defaultdict(set)
    for t in tracks:
        canon = TRACK_ALIASES.get(t["raw_name"], t["raw_name"])
        canon_variants[canon].add(t["raw_name"])
        for pid in t["presentation_ids"]:
            pres_tracks[pid].add(canon)
    track_names = sorted(canon_variants)
    short_of = {t: TRACK_SHORT.get(t, t) for t in track_names}

    # ---- index speakers --------------------------------------------------
    spk_by_id = {s["presenter_id"]: s for s in speakers}
    # Disambiguate people who share a display name.
    name_counts = defaultdict(list)
    for s in speakers:
        name_counts[safe(s["name"])].append(s["presenter_id"])
    note_name = {}
    for nm, ids in name_counts.items():
        for i, pid in enumerate(sorted(ids)):
            note_name[pid] = nm if len(ids) == 1 else f"{nm} ({pid})"

    sessions = sorted(sessions, key=lambda s: (s["date"] or "", s["order"]))

    # Session note titles must be unique too (repeated breaks etc.).
    sess_note = {}
    used = defaultdict(int)
    for s in sessions:
        base = safe(s["title"]) or f"Session {s['presentation_id']}"
        used[base] += 1
        stem = f"{s['date']} {base}"
        if used[base] > 1:
            stem = f"{s['date']} {base} ({used[base]})"
        sess_note[s["presentation_id"]] = stem

    speaker_sessions = defaultdict(list)
    for s in sessions:
        for sp in s.get("speakers", []):
            speaker_sessions[sp["presenter_id"]].append(s)

    track_sessions = defaultdict(list)
    for s in sessions:
        for t in pres_tracks.get(s["presentation_id"], ()):
            track_sessions[t].append(s)

    track_speakers = defaultdict(set)
    for t, ss in track_sessions.items():
        for s in ss:
            for sp in s.get("speakers", []):
                track_speakers[t].add(sp["presenter_id"])

    # ---- session notes ---------------------------------------------------
    for s in sessions:
        pid = s["presentation_id"]
        start, end = parse_time(s["time_raw"])
        stracks = sorted(pres_tracks.get(pid, ()))
        spk_links = [f"[[{note_name[x['presenter_id']]}]]" for x in s.get("speakers", [])
                     if x["presenter_id"] in note_name]
        is_session = s["build_code"] == "P"
        body = [
            fm([
                ("type", "session"),
                ("category", "session" if is_session else "logistics"),
                ("conference", CONF),
                ("date", s["date"]),
                ("weekday", s["weekday"]),
                ("start", start),
                ("end", end),
                ("location", s.get("location", "")),
                ("topics", [short_of[t] for t in stracks]),
                ("speakers", [note_name[x["presenter_id"]]
                              for x in s.get("speakers", [])
                              if x["presenter_id"] in note_name]),
                ("presentation_id", pid),
                ("url", f"{EVENTSCRIBE}/fsPopup.asp?PresentationID={pid}&mode=presInfo"),
                ("tags", ["abms2026", "session" if is_session else "logistics"]),
            ]),
            "",
            f"# {s['title']}",
            "",
            f"**{s['weekday']}, {s['date']}** · {s['time_raw']}"
            + (f" · {s['location']}" if s.get("location") else ""),
            "",
        ]
        if stracks:
            body += ["**Topic:** " + ", ".join(f"[[{short_of[t]}]]" for t in stracks), ""]
        if s.get("speakers"):
            body += ["## Speakers", ""]
            for x in s["speakers"]:
                link = f"[[{note_name[x['presenter_id']]}]]" if x["presenter_id"] in note_name else x["name"]
                aff = f" — {x['affiliation']}" if x["affiliation"] else ""
                body.append(f"- {link}{aff}")
            body.append("")
        if s.get("description"):
            body += ["## Description", "", s["description"], ""]
        body += [
            "## Links",
            "",
            f"- [[{CONF}]]",
            f"- [[{s['date']} Schedule]]",
            f"- [View on EventScribe]({EVENTSCRIBE}/fsPopup.asp?PresentationID={pid}&mode=presInfo)",
        ]
        write(os.path.join(VAULT, "Sessions", sess_note[pid] + ".md"), "\n".join(body))

    # ---- speaker notes ---------------------------------------------------
    for sp in speakers:
        pid = sp["presenter_id"]
        mine = speaker_sessions.get(pid, [])
        mytracks = sorted({t for s in mine for t in pres_tracks.get(s["presentation_id"], ())})
        # Best-known role/org from any session appearance.
        role = org = ""
        for s in mine:
            for x in s.get("speakers", []):
                if x["presenter_id"] == pid:
                    role = role or x.get("role", "")
                    org = org or x.get("organization", "")
        socials = sp.get("socials", {})
        body = [
            fm([
                ("type", "speaker"),
                ("conference", CONF),
                ("name", sp["name"]),
                ("role", role),
                ("organization", org),
                ("title_line", sp.get("title", "")),
                ("topics", [short_of[t] for t in mytracks]),
                ("sessions", [sess_note[s["presentation_id"]] for s in mine]),
                ("session_count", len(mine)),
                ("photo", sp.get("photo", "")),
                ("presenter_id", pid),
                ("url", f"{EVENTSCRIBE}/ajaxcalls/presenterInfo.asp?PresenterId={pid}"),
                ("tags", ["abms2026", "speaker"]),
            ]),
            "",
            f"# {sp['name']}",
            "",
        ]
        if sp.get("title"):
            body += [f"*{sp['title']}*", ""]
        if sp.get("photo"):
            body += [f"![{sp['name']}|180]({sp['photo']})", ""]
        if mytracks:
            body += ["**Topics:** " + ", ".join(f"[[{short_of[t]}]]" for t in mytracks), ""]
        if mine:
            body += ["## Sessions", ""]
            for s in mine:
                body.append(
                    f"- [[{sess_note[s['presentation_id']]}|{s['title']}]] "
                    f"— {s['weekday']} {s['date']}, {s['time_raw']}"
                )
            body.append("")
        else:
            body += ["> [!note] Listed in the speaker directory with no session assigned.", ""]
        if sp.get("bio"):
            body += ["## Biography", "", sp["bio"], ""]
        if socials:
            body += ["## Elsewhere", ""]
            for k, v in sorted(socials.items()):
                body.append(f"- {k.title()}: {v}")
            body.append("")
        body += ["## Links", "", f"- [[{CONF}]]",
                 f"- [Profile on EventScribe]({EVENTSCRIBE}/ajaxcalls/presenterInfo.asp?PresenterId={pid})"]
        write(os.path.join(VAULT, "Speakers", note_name[pid] + ".md"), "\n".join(body))

    # ---- topic notes -----------------------------------------------------
    for t in track_names:
        ss = sorted(track_sessions.get(t, []), key=lambda x: (x["date"], x["order"]))
        spks = sorted(track_speakers.get(t, ()), key=lambda p: spk_by_id[p]["name"])
        variants = sorted(canon_variants[t] - {t})
        body = [
            fm([
                ("type", "topic"),
                ("conference", CONF),
                ("official_name", t),
                ("session_count", len(ss)),
                ("speaker_count", len(spks)),
                ("sessions", [sess_note[x["presentation_id"]] for x in ss]),
                ("speakers", [note_name[p] for p in spks]),
                ("tags", ["abms2026", "topic"]),
            ]),
            "",
            f"# {short_of[t]}",
            "",
            f"**Official track name:** {t}",
            "",
        ]
        if variants:
            body += ["> [!warning] Source data variants merged into this topic",
                     ""] + [f"> - {v}" for v in variants] + [""]
        body += [f"{len(ss)} session{'s' if len(ss) != 1 else ''} · "
                 f"{len(spks)} speaker{'s' if len(spks) != 1 else ''}", ""]
        body += ["## Sessions", ""]
        for x in ss:
            body.append(f"- **{x['date']}** [[{sess_note[x['presentation_id']]}|{x['title']}]]")
        body += ["", "## Speakers", ""]
        for p in spks:
            body.append(f"- [[{note_name[p]}]]")
        body += ["", "## Links", "", f"- [[{CONF}]]"]
        write(os.path.join(VAULT, "Topics", safe(short_of[t]) + ".md"), "\n".join(body))

    # ---- daily schedule notes -------------------------------------------
    by_date = defaultdict(list)
    for s in sessions:
        by_date[s["date"]].append(s)
    for date in sorted(by_date):
        ss = sorted(by_date[date], key=lambda x: x["order"])
        wd = ss[0]["weekday"]
        body = [
            fm([
                ("type", "schedule"),
                ("conference", CONF),
                ("date", date),
                ("weekday", wd),
                ("session_count", len(ss)),
                ("tags", ["abms2026", "schedule"]),
            ]),
            "",
            f"# {wd}, {date}",
            "",
            f"{len(ss)} agenda items.",
            "",
            "| Time | Item | Topic | Speakers |",
            "| --- | --- | --- | --- |",
        ]
        for s in ss:
            start, end = parse_time(s["time_raw"])
            tks = ", ".join(f"[[{short_of[t]}]]"
                            for t in sorted(pres_tracks.get(s["presentation_id"], ())))
            sp = ", ".join(f"[[{note_name[x['presenter_id']]}]]"
                           for x in s.get("speakers", [])
                           if x["presenter_id"] in note_name)
            body.append(
                f"| {start}–{end} | [[{sess_note[s['presentation_id']]}\\|{s['title']}]] "
                f"| {tks} | {sp} |"
            )
        body += ["", "## Links", "", f"- [[{CONF}]]"]
        write(os.path.join(VAULT, "Schedule", f"{date} Schedule.md"), "\n".join(body))

    # ---- map of content --------------------------------------------------
    real = [s for s in sessions if s["build_code"] == "P"]
    speaking = [s for s in speakers if speaker_sessions.get(s["presenter_id"])]
    top = sorted(speaking, key=lambda s: -len(speaker_sessions[s["presenter_id"]]))[:10]
    body = [
        fm([
            ("type", "moc"),
            ("conference", CONF),
            ("dates", f"{min(by_date)} to {max(by_date)}"),
            ("sessions", len(real)),
            ("logistics_items", len(sessions) - len(real)),
            ("speakers", len(speakers)),
            ("topics", len(track_names)),
            ("source", "https://www.abmsconference.com/topics-2026"),
            ("tags", ["abms2026", "moc"]),
        ]),
        "",
        f"# {CONF}",
        "",
        f"September {min(by_date)[-2:]}–{max(by_date)[-2:]}, 2026 · "
        f"{len(real)} sessions · {len(speakers)} speakers · {len(track_names)} topics",
        "",
        "## Topics",
        "",
    ]
    for t in track_names:
        body.append(
            f"- [[{short_of[t]}]] — {len(track_sessions.get(t, []))} sessions, "
            f"{len(track_speakers.get(t, ()))} speakers"
        )
    body += ["", "## Schedule", ""]
    for date in sorted(by_date):
        wd = by_date[date][0]["weekday"]
        body.append(f"- [[{date} Schedule|{wd}, {date}]] — {len(by_date[date])} items")
    body += ["", "## Most-featured speakers", ""]
    for s in top:
        n = len(speaker_sessions[s["presenter_id"]])
        body.append(f"- [[{note_name[s['presenter_id']]}]] — {n} session{'s' if n != 1 else ''}")
    body += [
        "",
        "## Browse",
        "",
        "```dataview",
        "TABLE session_count AS Sessions, organization AS Organization",
        'FROM #speaker',
        "SORT session_count DESC, name ASC",
        "```",
        "",
        "## About this vault",
        "",
        "Generated from the ABMS Conference 2026 EventScribe programme.",
        "Rebuild with `python3 scrape.py && python3 build_vault.py`.",
        "",
        f"- Source: <https://www.abmsconference.com/topics-2026>",
        f"- Programme: <{EVENTSCRIBE}/agenda.asp?pfp=BrowsebyDay>",
    ]
    write(os.path.join(VAULT, f"{CONF}.md"), "\n".join(body))

    n = sum(len(files) for _, _, files in os.walk(VAULT))
    print(f"Vault written to {VAULT}")
    print(f"  {len(sessions)} sessions ({len(real)} substantive, {len(sessions)-len(real)} logistics)")
    print(f"  {len(speakers)} speakers ({len(speaking)} with sessions)")
    print(f"  {len(track_names)} topics, {len(by_date)} schedule days")
    print(f"  {n} notes total")


if __name__ == "__main__":
    main()
