# ABMS Conference 2026 — Obsidian Vault

An Obsidian vault of the topics, sessions and speakers at ABMS Conference 2026
(September 15–18, 2026), scraped from the conference programme.

## Usage

```bash
python3 scrape.py          # fetch + parse -> data/abms2026.json
python3 build_vault.py     # generate the "ABMS 2026" vault
python3 scrape.py --refresh   # bypass the on-disk HTTP cache
```

Open the `ABMS 2026` folder as a vault in Obsidian.

## Where the data comes from

`abmsconference.com/topics-2026` is a Squarespace page that embeds the real
programme from **EventScribe** (Cadmium) via a `pym.js` iframe. The scraper
skips the Squarespace wrapper and reads EventScribe directly:

| Data | Endpoint |
| --- | --- |
| Agenda (all days) | `agenda.asp?pfp=BrowsebyDay&all=1` |
| Topic tracks | `SearchByBucket.asp?f=TrackName` |
| Speaker directory | `biography.asp?pfp=Speakers` |
| Session detail | `fsPopup.asp?PresentationID=…&mode=presInfo` |
| Speaker detail | `ajaxcalls/presenterInfo.asp?PresenterId=…` |

All pages are server-rendered, so plain HTTP works — no browser automation.
Responses are cached under `data/cache/` so re-runs are free.

Fetches shell out to `curl` because this machine's Python trust store rejects
the origin's certificate chain while curl's accepts it.

## Vault structure

```
ABMS 2026/
  ABMS Conference 2026.md     Map of content: topics, days, top speakers
  Topics/     (5)             One note per track, listing its sessions + speakers
  Sessions/   (82)            One note per agenda item
  Speakers/   (123)           Bio, affiliation, photo, sessions
  Schedule/   (4)             One note per conference day, as a table
```

Every note carries YAML frontmatter for Dataview (`type`, `topics`, `speakers`,
`sessions`, `date`, `start`/`end`, `tags`, …) and links to every related note,
so topics, sessions and speakers are reachable from each other in both
directions. 1,279 wikilinks, all resolving.

Sessions are tagged `#session` or `#logistics` — the latter covers breakfasts,
breaks, receptions and exhibitor showcases, so you can filter them out:

```dataview
TABLE start, topics, speakers FROM #session WHERE category = "session"
```

## Notes on source-data quality

The scrape reproduces the programme as published; these quirks are the source's,
not the scraper's.

- **Duplicate tracks from typos.** EventScribe exposes 9 track buckets that are
  really 5 topics. `build_vault.py` merges them via `TRACK_ALIASES` and each
  topic note records the raw variants it absorbed:
  - "Board Cert**f**ication and Professionalism" → Board Certification and Professionalism
  - "Artificial Intelligence (**Al**)" (lowercase L) → Artificial Intelligence (AI)
  - "Emerging Landscape of the Physician **Work Force**" and
    "Programs/The Emerging Landscape…" → The Emerging Landscape of the Physician Workforce
- **Incomplete track assignment.** Only 40 of 82 agenda items sit in a track
  bucket at all; 10 of the 50 substantive sessions — including both plenaries —
  have no topic assigned upstream. Those notes have `topics: []`.
- **Locations are mostly absent.** Only 2 agenda rows publish a room.
- Minor artefacts such as a speaker credential listed as "MD MD" are left as
  published.
