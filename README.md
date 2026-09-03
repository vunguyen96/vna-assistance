# vna-assistance

A local-first CLI note/task assistant for Windows. Capture reminders, tasks,
recurring duties, Jira tickets, and diary entries in plain natural language;
everything is parsed with local heuristics and stored in a single,
schema-evolving CSV under your home folder. A self-contained desktop viewer
(HTA) and an optional browser view let you see, complete, and add tasks with a
live, grouped, real-time UI.

No servers. No cloud. No database. Just Python, one CSV, and Windows.

## Features

- **Natural-language capture** — `/note` free text is parsed into structured
  fields (title, type, ticket, recurrence, due date/time, urgency, project,
  tags, …). Local regex/keyword/date heuristics run first; a stronger LLM is
  called only when confidence is low (and results are cached by text hash).
- **Schema-evolving storage** — one master CSV; new fields are added as columns
  and existing rows are backfilled. Automatic split into part files, adapting
  from date → date+project → project sharding as volume grows.
- **Desktop viewer (HTA)** — runs in `mshta.exe`, reads the CSV directly (no
  server). Active/Done tabs, tasks grouped by due window (overdue, due today,
  next 4h, next 12h, upcoming) with collapsible sections, per-card live
  countdowns, a real-time header clock, done/restore/delete, and a due-soon
  notification badge.
- **Add tasks from the UI** — a form with summary, tags, description, and an
  optional due date/time. **Create task** routes through Copilot CLI (smart
  parsing); **Create simple task** writes directly via the local Python CLI
  (instant, deterministic). Both run in the background with a progress bar.
- **Copilot CLI integration** — three skills and a sessionStart hook so Copilot
  can add, complete, and review tasks conversationally.
- **Browser view (optional)** — `index.html` + `app.js` for Chrome/Firefox via a
  tiny local static server.

## Requirements

- Windows (the HTA viewer uses `mshta.exe`; `cmd.exe` powers the background worker)
- Python 3.9+
- GitHub Copilot CLI (optional — only for the skills, hook, and smart add)
- `dateparser` (optional, recommended — better relative-date parsing)

## Install

```powershell
git clone <your-fork-url> vna-assistance
cd vna-assistance
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The installer:

1. creates the data folder (`%USERPROFILE%\vna-assistance`, or `VNA_HOME`);
2. installs the three skills into `%USERPROFILE%\.copilot\skills\`;
3. installs the sessionStart hook, patched to this repo's path;
4. installs `dateparser` (best effort);
5. creates a Desktop shortcut to the viewer.

Useful flags: `-DataDir <path>`, `-CopilotConfig <path>`, `-NoHook`,
`-NoShortcut`, `-NoDeps`. Remove everything with `uninstall.ps1`
(add `-PurgeData` to also delete your notes).

Nothing in the app hard-codes a machine path: the CLI and HTA resolve the data
folder from `%USERPROFILE%` (or `VNA_HOME`), and the HTA auto-detects the CLI
from its own location (override with `VNA_PROJECT`).

## Usage

### CLI

```powershell
python vna-assistance-cli.py note "On every wednesday do the morning duty"
python vna-assistance-cli.py note "email the team" --due "tomorrow 9am"
python vna-assistance-cli.py start-session          # relevant items on resume
python vna-assistance-cli.py show --days 7
python vna-assistance-cli.py done MON-1122          # complete a task
python vna-assistance-cli.py done "standup" --today # recurring: skip today only
python vna-assistance-cli.py migrate-schema
python vna-assistance-cli.py selftest               # run built-in unit tests
```

### Desktop viewer

Double-click the Desktop shortcut, or:

```powershell
mshta "web\vna-assistance.hta"
```

### Browser view

```powershell
web\serve.cmd
```

Serves the data folder at `http://localhost:8777/` and opens it. See
[`web/README.md`](web/README.md) for details.

## Copilot skills

Once installed, Copilot CLI can drive the store conversationally:

| Skill | Trigger examples |
|-------|------------------|
| `vna-assistance-note`   | "add a note…", "remember to…", "log a task…" |
| `vna-assistance-done`   | "mark done", "completed", "close MON-1122" |
| `vna-assistance-review` | "review my tasks", "what do I have to do" |

## Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `VNA_HOME` | Data folder (holds the CSV, parts, cache) | `%USERPROFILE%\vna-assistance` |
| `VNA_PROJECT` | Repo folder the HTA runs the CLI from | auto-detected |
| `LOCAL_LLM_PATH` | Local LLM runtime for the extraction fallback | unset |
| `OPENAI_API_KEY` | Enables the OpenAI extraction fallback | unset |

## Repository layout

```
vna-assistance/
├─ vna-assistance-cli.py        # the CLI (parsing, storage, schema evolution)
├─ requirements.txt             # optional Python deps
├─ install.ps1 / uninstall.ps1  # Windows setup
├─ copilot/
│  ├─ skills/                   # vna-assistance-note / -done / -review
│  └─ hooks/                    # sessionStart reminder hook (templated)
└─ web/
   ├─ vna-assistance.hta        # desktop viewer (ES5, mshta.exe)
   ├─ vna-assistance.ico        # app icon
   ├─ index.html / app.js / styles.css   # browser view
   ├─ open-today.mjs            # Node one-shot "today" printer
   ├─ serve.cmd                 # local static server launcher
   └─ README.md                 # viewer docs
```

## Data & storage

Notes live in `%USERPROFILE%\vna-assistance\vna-assistance.csv` (19 columns,
extended automatically as new fields appear). Part files, cache, decision
records, and `strategy.log` sit alongside it. The data folder is **not** part of
this repository (see `.gitignore`) — your notes stay on your machine.

## License

MIT — see [LICENSE](LICENSE).
