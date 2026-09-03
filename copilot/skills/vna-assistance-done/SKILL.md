---
name: vna-assistance-done
description: Mark a vna-assistance task as done so it is skipped from future reminders. Supports permanent completion and, for recurring tasks, "done for today" (--today) which skips only the current occurrence and reminds again next iteration. Use when the user says "mark done", "task done", "completed", "finished", "close MON-1122", "done with today's standup", "did this week's duty", or reports a stored task is complete.
allowed-tools:
  - shell
  - powershell
metadata:
  schema-version: 1.0
  tags:
    - vna-assistance
    - tasks
    - done
    - reminders
    - cli
  version: 1.0.0
---

# vna-assistance-done

Mark a stored task as complete. Done items keep their history in the CSV but are
skipped from `start-session` / `show` reminders.

## When to use

Trigger on: "mark done", "task done", "completed", "finished", "close
<ticket>", "done with…", "I finished…", or any report that a previously stored
item is complete.

For a **recurring** task that is only finished for the current cycle (e.g. "did
today's standup", "done with this week's Monsoon duty"), use the **done for
today** variant (`--today`) so the reminder returns at the next iteration
instead of ending the series.

## Two completion modes

- **Permanent done** — the task is finished for good and should never remind
  again. Use for one-off tasks, or to intentionally end a recurring series.
- **Done for this occurrence** (`--today`) — for recurring tasks only. Marks the
  current cycle complete so it is skipped now, but the reminder returns at the
  next occurrence (next day for `daily`, next matching weekday for
  `weekly:<weekday>`, next week/month for `weekly`/`monthly`). The task stays
  open; its status is not changed.

Decision rule: if the task is recurring and the user finished only this cycle,
add `--today`. Otherwise omit it.

## How to mark a task done

1. Identify which item the user means. Accept any of:
   - a numeric record **id** (e.g. `2`),
   - a **ticket** (e.g. `MON-1122`),
   - a distinctive **text substring** from the note (e.g. `Monsoon duty`).
   If the reference is ambiguous, first run
   `python .\vna-assistance-cli.py start-session` (or `show --days N`) to list
   items with their ids, then pick the right one.
2. Locate the CLI script `vna-assistance-cli.py` at the repository root
   (`F:\Monsoon\vna-assistance-cli.py`); search for it if it moved.
3. Run, from the repository root:

   ```powershell
   # permanent completion
   python .\vna-assistance-cli.py done "<id|ticket|text>"

   # recurring task, this occurrence only (reminds again next iteration)
   python .\vna-assistance-cli.py done "<id|ticket|text>" --today
   ```

4. Report the result. On success the command prints the affected id(s); on no
   match it prints `No open item matched …` — in that case list current items
   and ask the user which one.
5. Do not ask for extra confirmation when the identifier is unambiguous — mark
   it done immediately, then confirm.

## Behaviour

- Permanent done sets `status=done` and stamps `completed_at` on the matching
  row(s) in the master CSV (the source of truth for reminders). Part-file
  snapshots are left untouched by design.
- `--today` on a recurring task stamps `last_done`/`last_done_occurrence` and
  keeps `status=open`; the item is skipped only for the current occurrence and
  reappears at the next one. On a non-recurring task, `--today` behaves like a
  permanent done.
- Matching: exact id, case-insensitive ticket, or a text substring (min 3
  chars). Already-done items are not re-marked.
- After a permanent done, the item disappears from `start-session` and `show`
  output, even if it is recurring, due today, or urgent.
- Each completion is recorded in `%USERPROFILE%/vna-assistance/strategy.log`
  (`DONE` for permanent, `DONE_TODAY` for occurrence-only).

## Examples

- **"mark MON-1122 done"** → `python .\vna-assistance-cli.py done "MON-1122"`.
- **"I finished the Monsoon morning duty for good"** →
  `python .\vna-assistance-cli.py done "Monsoon morning duty"`.
- **"done with today's standup"** (recurring) →
  `python .\vna-assistance-cli.py done "standup" --today`.
- **"did this week's Monsoon duty"** (recurring) →
  `python .\vna-assistance-cli.py done "Monsoon duty" --today`.
- **"close task 2"** → `python .\vna-assistance-cli.py done "2"`.

## Related

- Add notes with the `vna-assistance-note` skill
  (`python .\vna-assistance-cli.py note "<text>"`).
- Review open items: `python .\vna-assistance-cli.py start-session`.
