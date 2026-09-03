# vna-assistance-web

A "poor" (no-server, no-dependency) task viewer. It reads the
`vna-assistance.csv` file directly and shows **all upcoming tasks**, grouped by
how soon they are due: **Due within 4 hours**, **Due within 12 hours**,
**Due today**, then **Coming** — each sorted by due time. The time-based
buckets apply to due dates that carry a time-of-day; date-only items due today
land in "Due today".

Several ways to use it — pick whichever fits. **For a true one-double-click,
auto-loading experience on Windows, use the HTA (option 1).**

## 1. HTA — double-click, auto-loads, no server, no picker (recommended)

Double-click **`vna-assistance.hta`**. It opens in Windows' `mshta.exe`, which
has full local file access, so it reads
`C:\Users\U813650\vna-assistance\vna-assistance.csv` **directly** and renders
your tasks immediately — no browser security prompt, no file picker, no server.
Click **Refresh** after adding notes to reload. Override the location with the
`VNA_HOME` environment variable.

`mshta.exe` is "Microsoft HTML Application Host", a built-in Windows program
that runs `.hta` files as trusted desktop apps (hence the local file access).

### Actions (HTA only)

Because the HTA runs as a trusted app, it can also **change** your tasks, not
just show them:

- **Add task** — click **+ Add task** in the top-right to open the task form,
  which has these fields:
  - **Summary** — a one-line title for the task.
  - **Tags** — click any existing tag to select it, and/or type new
    comma-separated tags in the box below (spaces become hyphens, e.g. `Milk
    Tea` &rarr; `milk-tea`).
  - **Description** — details and things to watch while doing the task.
  - **Due date & time** *(optional)* — an ISO value (`2026-09-05 15:30`) or
    natural language (`next friday 3pm`, `tomorrow noon`). It is parsed locally
    and overrides any date the assistant might infer from the text. Leave it
    empty to let the assistant work out the due date from the summary.

  The form has two create buttons:
  - **Create task** — concatenates the fields into a single note (the summary,
    then a `Tags: #tag1 #tag2` line, then a `Description: ...` line) and by
    default runs the **Copilot CLI** so the `vna-assistance-note` skill parses
    it (resolving relative dates like "next Monday" to absolute ones). This is
    smarter but can take a minute.
  - **Create simple task** — creates the task **directly with the local Python
    parser, with no Copilot CLI involved**. It is near-instant and fully
    deterministic; use it when you have already filled in the due date or do not
    need the assistant's help.

  Both buttons send the same concatenated text (plus the optional due via the
  CLI's `--due`). Press **Enter** in the Summary, Tags, or Due box to run
  **Create task**; the Description box keeps Enter for newlines. The add runs
  **in the background** while an animated **loading bar** shows under the tabs
  and the form is disabled, so the window stays responsive.
  The note text is handed to the CLI through a UTF-8 temp file
  (`_vna_note_input.txt` in your data folder), so quotes and special characters
  need no escaping. When it finishes a green toast appears in the bottom-right,
  the form clears and closes, and the list auto-refreshes with the new data; a
  red toast reports any failure. (Completion is detected via a
  `_vna_note_result.txt` flag the background job writes.)

  **Dedicated background shell.** To avoid paying the cost of spawning a fresh
  `cmd` (and `cd`-ing into the project) on every note, the app launches a single
  hidden worker `cmd.exe` when it opens, with its working directory pinned to the
  project. Each **Add task** just drops a job file that the worker picks up — so
  the shell is always warm and ready. (The Copilot CLI's own start-up still
  dominates the wall-clock time; the worker removes the per-note shell overhead
  and keeps a ready shell around.) The worker is tied to the app's lifetime two
  ways: on a normal close it receives a stop signal (`onunload`), and it also
  watches an app **heartbeat** file — if the heartbeat stops changing (app closed
  or crashed) it shuts itself down within a few seconds. Helper files it uses in
  your data folder: `_vna_worker.cmd`, `_vna_worker.lock`, `_vna_app.lock`,
  `_vna_job.cmd`, `_vna_stop`.
- **Done / Done today** — each card has a button. Plain tasks are marked done
  and drop off the reminders. Recurring tasks use **Done today**: the current
  occurrence is completed but it returns next iteration. A toast confirms the
  change and the list refreshes.
- **Delete** — every card (in both tabs) has a **Delete** button. After a
  confirmation prompt the task is **permanently removed** from the master CSV,
  so it disappears from the Active *and* Done tabs. A toast confirms it and the
  list refreshes.
- **Restore** — cards in the **Done** tab have a **Restore** button that reopens
  the task (clears its completed/snooze stamps) and moves it back to the Active
  tab. A toast confirms it and the list refreshes.

Each task card shows:

- **Title** — a clean one-line summary. If a task was created from the Add-task
  form, the inline `Tags:`/`Description:` suffix is stripped from the heading.
- **Live timer** — directly under the title, the due day (or time) followed by a
  **real-time countdown** that ticks every second (`in 1h 58m 59s`). It turns
  orange when the task is due within four hours and red once it is overdue
  (`overdue by ...`). Tasks without a due date or recurrence show no timer.
- **Labels** — every tag on the task appears as its own chip in the badge row,
  alongside the type, urgency, ticket, and project badges.
- **Details** — the meta list shows only fields that carry real information.
  The full **Description** is shown (line breaks preserved, never truncated),
  and empty or default values (`n/a`, unset impact, the generic "ask team"
  fallback) are omitted rather than displayed.

The view has two tabs:

- **Active** — the default: today's tasks on top (high priority), then upcoming.
  The header line under **Tasks** shows a **live clock** (`2026-09-03 17:32:44`,
  updating every second) followed by the today / upcoming / total counts.
- **Done** — every completed task, most recently completed first. Recurring
  tasks snoozed with **Done today** stay in Active (they return next
  iteration); only truly completed tasks appear here.

All actions shell out to `vna-assistance-cli.py` in `F:\Monsoon`. Configure the
behaviour at the top of `vna-assistance.hta`:

- `USE_COPILOT` — `true` (default) routes **Add task** through the Copilot CLI,
  falling back to the Python CLI if Copilot is missing or fails. Set to `false`
  to always use the fast, deterministic Python CLI directly.
- `PROJECT_DIR`, `PYTHON`, `CLI` — where the code lives and how to run it.

The window/taskbar icon comes from `vna-assistance.ico`. Windows always shows
the generic `.hta` icon in Explorer, so for a custom icon on the thing you
click, use **`vna-assistance.lnk`** (a shortcut that launches the HTA with the
custom icon). Copy it to your Desktop or Start menu if you like.

Why this exists: browsers block `file://` pages from reading local files, so a
plain `index.html` double-click in Chrome/Edge cannot auto-load. The HTA sidesteps
that entirely while staying dependency-free.

## 2. Browser (static HTML, no service)

Open `index.html` in your browser. On load it automatically tries, in order:

1. the absolute default `C:\Users\U813650\vna-assistance\vna-assistance.csv`
   (via a `file://` URL — works in Firefox and when served),
2. `./vna-assistance.csv` next to `index.html`,
3. otherwise it shows the picker: click **Open CSV…** or drag the file in.

Chrome and Edge block `file://` pages from reading local files, so a plain
double-click there falls back to the picker. Use the HTA (option 1) or the
launcher below for guaranteed auto-load.

## 2b. Guaranteed auto-load in a browser (serve.cmd)

Double-click **`serve.cmd`** (needs Python). It serves your data folder at
`http://localhost:8777/` and opens the page, so `index.html` reads the **live**
CSV directly — auto-loading in every browser. Press `Ctrl+C` to stop. Editing
the CSV with the CLI and refreshing the page shows the latest data.

## 3. Node (reads the fixed path directly)

No picker, no browser — just print today's tasks:

```powershell
node open-today.mjs
```

It reads `%USERPROFILE%\vna-assistance\vna-assistance.csv` — by default
`C:\Users\U813650\vna-assistance\vna-assistance.csv` (override with the
`VNA_HOME` environment variable). Requires Node 16+ (uses ES modules).

## What gets shown

Ported from `vna-assistance-cli.py`:

- Skip items with `status = done`.
- For recurring items, skip when `last_done_occurrence` matches the current
  occurrence key (daily → date, `weekly:<weekday>` → that week's weekday date,
  `weekly` → ISO week, `monthly` → `YYYY-MM`).
- Otherwise show every task that is **recurring**, **urgent**, or **has a due
  date** (today, overdue, or future). Plain notes with no date/urgency/recurrence
  are hidden.

Ordering (Active tab groups, most urgent first):

- **Due within 4 hours** — items whose due date carries a time-of-day that
  falls within the next 4 hours (overdue timed items included here too).
- **Due within 12 hours** — timed items due within the next 12 hours.
- **Due today** — date-only items due today or overdue, urgency ∈ {urgent,
  asap, high}, or a recurring occurrence on today. (Items without a
  time-of-day cannot fall into the 4h/12h buckets, so they land here.)
- **Coming** — everything else (future days), including timed items more
  than 12 hours out.
- Every group is sorted by due time (earliest first), then urgency.
- Each group header is **clickable to collapse or expand** it; the header shows
  a caret (down = open, right = collapsed) and the item count. Collapse state is
  remembered while the app stays open and applies to both the Active and Done
  tabs.
- Only the task list scrolls: the header, task form, and tabs stay pinned, and
  the scrollbar belongs to the Active/Done list area rather than the window.
- **Groups update in real time.** The app re-checks due times every 30 seconds,
  so a task automatically moves between buckets as its deadline approaches
  (Coming &rarr; Due within 12 hours &rarr; Due within 4 hours &rarr; Due today)
  without a manual refresh.
- **Due notification badge.** When a task slips from **Coming** into any due
  bucket, a badge appears in the bottom-right corner showing how many tasks just
  became due and their titles. Click the badge to dismiss it.
- A note captures a due **day and time** when you state one (e.g. "next Monday
  5pm", "tomorrow at 09:30", "at noon"); the time drives the 4h/12h buckets.
  Notes with only a day land in **Due today** / **Coming**.
- Each item shows: what (title), when (due date, with time when set, or
  recurrence), urgency, how (assignee, else impact, else `actionable: ask
  team`), and impact.

## Files

- `vna-assistance.hta` — **self-contained** double-click viewer (reads the CSV
  directly via `mshta.exe`; recommended for one-click auto-load).
- `vna-assistance.ico` — app icon used by the HTA window and the shortcut.
- `vna-assistance.lnk` — shortcut that launches the HTA with the custom icon
  (copy to Desktop/Start menu for a nicer entry point).
- `index.html` — markup and layout for the browser viewer.
- `styles.css` — dark, dependency-free styling.
- `app.js` — CSV parser + relevance logic + rendering + auto-load.
- `serve.cmd` — local launcher for guaranteed browser auto-load.
- `open-today.mjs` — Node CLI that reads the CSV path directly.
