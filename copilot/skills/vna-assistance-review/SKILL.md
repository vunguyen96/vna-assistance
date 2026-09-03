---
name: vna-assistance-review
description: Actively review relevant vna-assistance tasks — items that are due today, recurring, or urgent (and optionally recent history). Use when the user says "review my tasks", "what do I have to do", "show my reminders", "what's relevant today", "any open tasks", "start-session", or wants a rundown of outstanding work.
allowed-tools:
  - shell
  - powershell
metadata:
  schema-version: 1.0
  tags:
    - vna-assistance
    - tasks
    - review
    - reminders
    - cli
  version: 1.0.0
---

# vna-assistance-review

Give the user an on-demand rundown of their relevant tasks from the local
vna-assistance store. Relevant means: due today, recurring, or urgency in
{urgent, asap, high}. Completed (done) items are excluded automatically.

## When to use

Trigger on: "review my tasks", "what do I have to do", "show my reminders",
"what's relevant today", "any open tasks", "run start-session", or any request
to look over outstanding work.

## How to review

1. Locate the CLI script `vna-assistance-cli.py` at the repository root
   (`F:\Monsoon\vna-assistance-cli.py`); search for it if it moved.
2. Choose the command:
   - Default (today's relevant items):
     ```powershell
     python .\vna-assistance-cli.py start-session
     ```
   - Wider window — include items from the last N days (the user says
     "this week", "last 3 days", etc.):
     ```powershell
     python .\vna-assistance-cli.py show --days N
     ```
     Map "this week" -> `--days 7`, "today" -> `start-session`.
3. Present the output as a clean, prioritised list. Order by urgency
   (urgent/asap/high first), then due today, then recurring. For each item show:
   **what** (title), **when** (due_date or recurrence), **urgency**,
   **how-to-do**, and **impact**.
4. Flag any item whose how-to-do is `actionable: ask team` — it still needs an
   owner; suggest assigning it.
5. Offer next steps: mark an item done (via the `vna-assistance-done` skill /
   `done` command) or add a new note (via the `vna-assistance-note` skill).
6. Do not modify any data during a review — this is read-only.

## Interpreting fields

- `when`: an ISO date means it is due; `weekly:wednesday` / `daily` means it
  recurs.
- `urgency`: `normal` when unset; escalate `urgent`/`high` to the top.
- `how`: `assigned to <name>` when an owner exists, otherwise
  `actionable: ask team`.

## Examples

- **"review my tasks"** → `python .\vna-assistance-cli.py start-session`,
  then present the prioritised list.
- **"what do I have this week?"** → `python .\vna-assistance-cli.py show --days 7`.
- **"anything urgent?"** → run `start-session`, then filter the output to
  urgency in {urgent, asap, high}.

## Related

- Add a task: `vna-assistance-note` (`python .\vna-assistance-cli.py note "..."`).
- Complete a task: `vna-assistance-done`
  (`python .\vna-assistance-cli.py done "<id|ticket|text>"`).
- Reviews also run automatically at session start via the
  `vna-assistance-reminder` hook.
