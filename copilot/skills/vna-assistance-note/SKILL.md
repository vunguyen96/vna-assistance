---
name: vna-assistance-note
description: Add a note/task/diary entry to the local vna-assistance store from natural language. Use when the user says "/note ...", "add a note", "log a task", "remember to ...", "note down ...", or wants to capture a reminder, ticket, recurring duty, or diary entry into the vna-assistance CSV.
allowed-tools:
  - shell
  - powershell
metadata:
  schema-version: 1.0
  tags:
    - vna-assistance
    - notes
    - tasks
    - cli
  version: 1.2.0
---

# vna-assistance-note

Capture a free-text note into the local vna-assistance store. Parsing runs
local heuristics first and only calls an LLM when confidence is low, so this
skill is fast and token-cheap.

## When to use

Trigger on any of: `/note <text>`, "add a note", "log a task", "remember to…",
"note down…", "capture this reminder", or when the user dictates a task,
recurring duty, Jira ticket follow-up, or diary entry to store.

## How to add a note

1. Take the user's raw note text (everything after `/note`, or the whole
   request when the intent is clearly "add a note"). Do **not** rewrite,
   summarize, or translate it — pass it through verbatim so the heuristics see
   the original signals (ticket IDs, "every wednesday", "PROD", etc.).
2. Locate the CLI script `vna-assistance-cli.py` at the repository root
   (`F:\Monsoon\vna-assistance-cli.py`). If it is elsewhere, search for
   `vna-assistance-cli.py` first.
3. Run, from the repository root, quoting the text as a single argument:

   ```powershell
   python .\vna-assistance-cli.py note "<RAW_TEXT>"
   ```

   Escape any embedded double quotes in the text (`\"`).
4. The command prints the stored record as JSON. Read it back to the user and
   confirm the key extracted fields: `type`, `project`, `ticket`,
   `recurrence`, `due_date`, `urgency`, `tags`, and `confidence`. When the note
   contained a relative date (e.g. "next Monday", "tomorrow 5pm"), explicitly
   confirm the **resolved absolute `due_date`** (e.g. `2026-09-07` or
   `2026-09-07T17:00`) so the user sees what was stored.
5. If `assignee` is empty for a task that needs delegation, tell the user it is
   **actionable: ask team** (this is how session-resume will surface it).
6. Do not ask for extra confirmation before storing — add the note immediately,
   then report the result.

## Static resolution (context-independent dates)

Relative time references are resolved to **absolute dates (and times, when a
time of day is stated)** at capture time and stored in `due_date`. This makes
each record self-contained: it reads correctly later no matter when
session-resume or the web viewer loads it. The original wording is kept verbatim
in `raw_text`; only the structured `due_date` is made absolute.

Resolved against the moment the note is saved (example base: Thu 2026-09-03 13:00):

| You write | Stored `due_date` |
| --- | --- |
| `today` | `2026-09-03` |
| `tomorrow` | `2026-09-04` |
| `next Monday` / `on monday` | `2026-09-07` |
| `this friday` | `2026-09-04` |
| `in 3 days` | `2026-09-06` |
| `in 2 weeks` | `2026-09-17` |
| `next week` | `2026-09-07` (next Monday) |
| `next month` | `2026-10-01` |
| `end of week` | `2026-09-04` (Friday) |
| `07/09/2026` (day-first) / `15.10.2026` | `2026-09-07` / `2026-10-15` |
| `2026-11-01` (ISO) | `2026-11-01` |
| `next Monday at 5pm` | `2026-09-07T17:00` |
| `tomorrow 09:30` | `2026-09-04T09:30` |
| `at noon` (time only) | `2026-09-03T12:00` (today, or tomorrow if past) |

A **time of day** is captured only when unambiguous — a colon (`HH:MM`), an
`am`/`pm` suffix, or the words `noon`/`midday`/`midnight`. A bare number (e.g.
"at 5") is ignored to avoid mistaking ticket ids or counts for a time. When a
time is present the viewer uses it to sort tasks into the *due within 4 hours* /
*12 hours* groups, so prefer stating an explicit time when it matters.

Recurring duties are stored as context-independent tokens too
(`every wednesday` → `recurrence=weekly:wednesday`), so reminders recur without
needing a fixed date.

Because resolution uses the machine clock at capture time, pass the text
through **verbatim** — the CLI does the math. Do not pre-compute dates yourself
or rewrite the note.

## Storage location

Records go to the master CSV and part files under
`%USERPROFILE%/vna-assistance/` (override with the `VNA_HOME` env var). The
schema evolves automatically and files split by date (10 records per part).

## Extracted fields

`id, timestamp, title, type (task|note|diary), ticket, recurrence, due_date,
urgency, impact, project, assignee, tags, raw_text, source, confidence`

## Examples

- **"/note On every wednesday, I have to do the Monsoon morning duty, and
  checking the production deployment (assign to right person if possible)"**
  → runs `python .\vna-assistance-cli.py note "..."`; expect
  `type=task`, `recurrence=weekly:wednesday`, `project=Monsoon`,
  `tags=production`, `assignee` empty → actionable: ask team.

- **"/note On jira ticket MON-1122, need to ask other team how to config env in
  PROD."** → `type=task`, `ticket=MON-1122`, `project=MON`, `tags=prod`.

- **"/note Prepare the board deck for next Monday, high priority"** (captured on
  Thu 2026-09-03) → `type=task`, `urgency=high`, and the relative "next Monday"
  is stored as the absolute `due_date=2026-09-07`.

## Related

- To review stored items, run `python .\vna-assistance-cli.py start-session`
  or `python .\vna-assistance-cli.py show --days N`.
- To repair/evolve columns, run `python .\vna-assistance-cli.py migrate-schema`.
