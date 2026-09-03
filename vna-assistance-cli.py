#!/usr/bin/env python3
"""vna-assistance: a local-first CLI note/task assistant.

Ingests /note free text, extracts structured fields with local heuristics
(regex + optional dateparser + keyword lists), falls back to an LLM only when
heuristic confidence < 0.6, stores rows in a schema-evolving master CSV, splits
storage into part files, and prints a session-resume summary.

CLI:
    python vna-assistance-cli.py note "<text>"
    python vna-assistance-cli.py start-session
    python vna-assistance-cli.py show --days N
    python vna-assistance-cli.py done <id|ticket|text> [--today]
    python vna-assistance-cli.py migrate-schema
    python vna-assistance-cli.py session-hook     # sessionStart hook JSON
    python vna-assistance-cli.py selftest        # run built-in unit tests

Install (minimal):
    pip install dateparser            # optional but recommended
    pip install openai                # optional, only for OpenAI fallback

Environment:
    LOCAL_LLM_PATH   if set and exists -> use local runtime for fallback
    OPENAI_API_KEY   used by the OpenAI fallback
    VNA_HOME         override base dir (default: %USERPROFILE%/vna-assistance)
"""
from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import hashlib
import json
import os
import re
import sys
from typing import Optional

# ----------------------------------------------------------------------------
# Optional dependency: dateparser (graceful fallback to a tiny built-in parser)
# ----------------------------------------------------------------------------
try:
    import dateparser  # type: ignore
    _HAS_DATEPARSER = True
except Exception:  # pragma: no cover - environment dependent
    dateparser = None  # type: ignore
    _HAS_DATEPARSER = False

# ----------------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------------
# Default store location: <user home>\vna-assistance.
# Override at runtime with the VNA_HOME environment variable.
DEFAULT_HOME = os.path.join(os.path.expanduser("~"), "vna-assistance")
BASE_DIR = os.environ.get("VNA_HOME", DEFAULT_HOME)
MASTER_CSV = os.path.join(BASE_DIR, "vna-assistance.csv")
PARTS_DIR = os.path.join(BASE_DIR, "parts")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
DECISIONS_DIR = os.path.join(BASE_DIR, "decisions")
STRATEGY_LOG = os.path.join(BASE_DIR, "strategy.log")

RECORDS_PER_PART = 10
DAILY_PROJECT_SHARD_THRESHOLD = 100

# Canonical schema. New fields discovered later are appended (schema evolution).
SCHEMA = [
    "id", "timestamp", "title", "type", "ticket", "recurrence", "due_date",
    "urgency", "impact", "project", "assignee", "tags", "raw_text", "source",
    "confidence", "status", "completed_at", "last_done", "last_done_occurrence",
]

STATUS_OPEN = "open"
STATUS_DONE = "done"

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

URGENCY_KEYWORDS = {
    "urgent": "urgent", "asap": "urgent", "immediately": "urgent",
    "critical": "urgent", "blocker": "urgent",
    "high": "high", "important": "high", "priority": "high",
    "low": "low", "whenever": "low", "someday": "low",
}

TASK_VERBS = (
    "do", "check", "checking", "ask", "need to", "must", "have to", "fix",
    "deploy", "review", "config", "configure", "update", "create", "assign",
    "prepare", "investigate", "follow up",
)

DIARY_MARKERS = ("today i", "yesterday i", "diary:", "dear diary", "i felt")

# Known project keywords (case-insensitive). Extend as needed.
PROJECT_KEYWORDS = ("monsoon",)

ENV_TAGS = ("prod", "production", "staging", "dev", "test", "uat")


# ----------------------------------------------------------------------------
# Utilities
# ----------------------------------------------------------------------------
def _now_iso() -> str:
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _ensure_dirs() -> None:
    for d in (BASE_DIR, PARTS_DIR, CACHE_DIR, DECISIONS_DIR):
        os.makedirs(d, exist_ok=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _log_strategy(message: str) -> None:
    _ensure_dirs()
    with open(STRATEGY_LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{_now_iso()} {message}\n")


# ----------------------------------------------------------------------------
# Heuristic date parsing
# ----------------------------------------------------------------------------
def _add_months(d: dt.date, n: int) -> dt.date:
    """Add n calendar months to a date, clamping the day to the month length."""
    month_index = d.month - 1 + n
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return dt.date(year, month, min(d.day, last_day))


def parse_due_date(text: str, base: Optional[dt.datetime] = None) -> Optional[str]:
    """Resolve a due date to an absolute ISO date string, else None.

    Relative expressions are resolved against ``base`` (the capture time) so the
    stored value is static and reads correctly regardless of when it is loaded
    later. Understood forms:

    - ``today`` / ``tomorrow``
    - ``in N days`` / ``in N weeks`` / ``in N months``
    - ``this|next|coming|on|by|due <weekday>`` (nearest upcoming weekday;
      ``this <weekday>`` may resolve to today)
    - ``next week`` (next Monday) / ``next month`` (1st) / ``end of week`` (Fri)
    - ISO ``YYYY-MM-DD`` and day-first ``DD/MM/YYYY`` or ``DD.MM.YYYY``
    - anything ``dateparser`` understands after ``on|by|due`` (when installed)
    """
    base = base or dt.datetime.now()
    today = base.date()
    low = text.lower()
    weekday_re = "|".join(WEEKDAYS)

    if re.search(r"\btoday\b", low):
        return today.isoformat()
    if re.search(r"\btomorrow\b", low):
        return (today + dt.timedelta(days=1)).isoformat()

    m = re.search(r"\bin\s+(\d+)\s+days?\b", low)
    if m:
        return (today + dt.timedelta(days=int(m.group(1)))).isoformat()
    m = re.search(r"\bin\s+(\d+)\s+weeks?\b", low)
    if m:
        return (today + dt.timedelta(weeks=int(m.group(1)))).isoformat()
    m = re.search(r"\bin\s+(\d+)\s+months?\b", low)
    if m:
        return _add_months(today, int(m.group(1))).isoformat()

    m = re.search(r"\b(this|next|coming|on|by|due)\s+(" + weekday_re + r")\b", low)
    if m:
        keyword, name = m.group(1), m.group(2)
        delta = (WEEKDAYS[name] - base.weekday()) % 7
        if keyword != "this" and delta == 0:
            delta = 7  # nearest upcoming occurrence, not today
        return (today + dt.timedelta(days=delta)).isoformat()

    if re.search(r"\bnext\s+week\b", low):
        delta = (7 - base.weekday()) % 7 or 7  # Monday of next week
        return (today + dt.timedelta(days=delta)).isoformat()
    if re.search(r"\bnext\s+month\b", low):
        return _add_months(today.replace(day=1), 1).isoformat()
    if re.search(r"\bend\s+of\s+(?:the\s+)?week\b", low):
        return (today + dt.timedelta(days=(4 - base.weekday()) % 7)).isoformat()

    # Explicit ISO-like date.
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if m:
        return m.group(1)

    # Day-first numeric date: DD/MM/YYYY or DD.MM.YYYY (2- or 4-digit year).
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b", text)
    if m:
        day, month, year = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        year += 2000 if year < 100 else 0
        try:
            return dt.date(year, month, day).isoformat()
        except ValueError:
            pass

    if _HAS_DATEPARSER:
        m = re.search(r"\b(?:by|due|on)\s+([A-Za-z0-9,\s/:-]+)$", text.strip())
        if m:
            parsed = dateparser.parse(  # type: ignore[union-attr]
                m.group(1),
                settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": base},
            )
            if parsed:
                return parsed.date().isoformat()
    return None


def _apply_ampm(hour: int, ampm: Optional[str]) -> int:
    """Fold a 12-hour clock reading into 24-hour form."""
    if ampm == "pm" and hour < 12:
        return hour + 12
    if ampm == "am" and hour == 12:
        return 0
    return hour


def parse_time_of_day(text: str) -> Optional[tuple]:
    """Extract an unambiguous time-of-day as ``(hour, minute)`` or None.

    Only clear times are accepted so ticket ids and dates are never mistaken for
    a time: a colon (``HH:MM``), an ``am``/``pm`` suffix, or the keywords
    ``noon``/``midday``/``midnight``. Bare numbers (e.g. "at 5") are ignored.
    """
    low = text.lower()
    if re.search(r"\b(noon|midday)\b", low):
        return (12, 0)
    if re.search(r"\bmidnight\b", low):
        return (0, 0)

    m = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b", low)
    if m:
        hour = _apply_ampm(int(m.group(1)), m.group(3))
        minute = int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)

    m = re.search(r"\b(\d{1,2})\s*(am|pm)\b", low)
    if m:
        hour = _apply_ampm(int(m.group(1)), m.group(2))
        if 0 <= hour <= 23:
            return (hour, 0)
    return None


def parse_due_datetime(text: str, base: Optional[dt.datetime] = None) -> Optional[str]:
    """Resolve a due date *and* time into a static ISO string, else None.

    - date + time -> ``YYYY-MM-DDTHH:MM``
    - date only   -> ``YYYY-MM-DD`` (unchanged behaviour)
    - time only   -> today at that time, rolled to tomorrow if already past
    """
    base = base or dt.datetime.now()
    date_iso = parse_due_date(text, base)
    tod = parse_time_of_day(text)

    if date_iso and tod:
        d = dt.date.fromisoformat(date_iso)
        return dt.datetime(d.year, d.month, d.day, tod[0], tod[1]).strftime("%Y-%m-%dT%H:%M")
    if date_iso:
        return date_iso
    if tod:
        anchor = base.replace(second=0, microsecond=0)
        when = dt.datetime(base.year, base.month, base.day, tod[0], tod[1])
        if when <= anchor:
            when += dt.timedelta(days=1)
        return when.strftime("%Y-%m-%dT%H:%M")
    return None


def parse_recurrence(text: str) -> Optional[str]:
    low = text.lower()
    m = re.search(r"every\s+(" + "|".join(WEEKDAYS) + r")", low)
    if m:
        return f"weekly:{m.group(1)}"
    if re.search(r"\bevery\s+day\b|\bdaily\b|\beach day\b", low):
        return "daily"
    if re.search(r"\bevery\s+week\b|\bweekly\b", low):
        return "weekly"
    if re.search(r"\bevery\s+month\b|\bmonthly\b", low):
        return "monthly"
    return None


# ----------------------------------------------------------------------------
# Core heuristic extractor
# ----------------------------------------------------------------------------
def heuristic_extract(raw_text: str, base: Optional[dt.datetime] = None) -> dict:
    """Extract structured fields using local heuristics only.

    Returns a dict following SCHEMA (without id). confidence reflects how many
    strong signals were detected.
    """
    base = base or dt.datetime.now()
    text = raw_text.strip()
    low = text.lower()
    signals = 0

    ticket = None
    m = re.search(r"\b([A-Z]{2,}-\d+)\b", text)
    if m:
        ticket = m.group(1)
        signals += 1

    recurrence = parse_recurrence(text)
    if recurrence:
        signals += 1

    due_date = parse_due_datetime(text, base)
    if due_date:
        signals += 1

    urgency = None
    for kw, val in URGENCY_KEYWORDS.items():
        if re.search(rf"\b{re.escape(kw)}\b", low):
            urgency = val
            signals += 1
            break

    is_task = bool(recurrence) or any(v in low for v in TASK_VERBS)
    is_diary = any(mk in low for mk in DIARY_MARKERS)
    note_type = "diary" if is_diary else ("task" if is_task else "note")
    if is_task or is_diary:
        signals += 1

    # Project: ticket prefix > known keyword.
    project = None
    if ticket:
        project = ticket.split("-", 1)[0]
    else:
        for kw in PROJECT_KEYWORDS:
            if kw in low:
                project = kw.capitalize()
                signals += 1
                break

    # Assignee: explicit @name or 'assign to <name>' (vague -> None).
    assignee = None
    m = re.search(r"@([A-Za-z0-9_.-]+)", text)
    if m:
        assignee = m.group(1)
        signals += 1
    else:
        m = re.search(r"assign(?:ed)?\s+to\s+([A-Z][A-Za-z]+)", text)
        if m and m.group(1).lower() not in ("right", "the", "someone"):
            assignee = m.group(1)
            signals += 1

    # Tags: #hashtags + environment keywords.
    tags = re.findall(r"#([A-Za-z0-9_-]+)", text)
    tags += [e for e in ENV_TAGS if re.search(rf"\b{e}\b", low)]
    # Dedupe preserving order, normalise.
    seen: dict[str, None] = {}
    for t in tags:
        seen.setdefault(t.lower(), None)
    tags_str = ";".join(seen.keys()) if seen else None

    title = _make_title(text)

    # Confidence: scaled by number of strong signals, capped at 0.95.
    confidence = round(min(0.35 + 0.15 * signals, 0.95), 2)

    return {
        "timestamp": _now_iso(),
        "title": title,
        "type": note_type,
        "ticket": ticket,
        "recurrence": recurrence,
        "due_date": due_date,
        "urgency": urgency,
        "impact": None,
        "project": project,
        "assignee": assignee,
        "tags": tags_str,
        "raw_text": raw_text,
        "source": "cli",
        "confidence": confidence,
        "status": STATUS_OPEN,
        "completed_at": None,
    }


def _make_title(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip().rstrip(".")
    cleaned = re.sub(r"^\s*(on|the)\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned[:120]


# ----------------------------------------------------------------------------
# LLM fallback (compact, cached) — provider-agnostic wrapper
# ----------------------------------------------------------------------------
LLM_PROMPT_TEMPLATE = (
    "You are a JSON extractor. Input: {raw}\n"
    "Return only valid JSON with keys:\n"
    "id,timestamp,title,type,ticket,recurrence,due_date,urgency,impact,"
    "project,assignee,tags,raw_text,source,confidence,explain\n"
    "Rules:\n"
    "- timestamp: ISO 8601 now if unknown.\n"
    "- due_date: ISO 8601 or null. Include the time as YYYY-MM-DDTHH:MM when a "
    "time of day is stated, else date-only YYYY-MM-DD.\n"
    "- recurrence: short token like \"weekly:wednesday\" or null.\n"
    "- urgency: one of {{urgent, high, medium, low}} or null.\n"
    "- confidence: number 0.0-1.0.\n"
    "- title: short summary <=120 chars.\n"
    "- explain: <=40 tokens.\n"
    "Return JSON only."
)


def select_model(text: str, heuristic_conf: float) -> dict:
    """Return a model-selection decision record with a cost/latency hint."""
    local_path = os.environ.get("LOCAL_LLM_PATH")
    if local_path and os.path.exists(local_path):
        return {
            "provider": "local", "model": os.path.basename(local_path),
            "cost": "none", "latency": "low-med", "best_for": "local-first",
        }
    high_impact = len(text) > 240 or bool(re.search(r"\b(prod|production|critical|blocker)\b", text.lower()))
    ambiguous = heuristic_conf < 0.45
    if ambiguous and high_impact:
        return {
            "provider": "openai", "model": "gpt-4o",
            "cost": "high", "latency": "med", "best_for": "ambiguous+high-impact",
        }
    return {
        "provider": "openai", "model": "gpt-3.5-turbo",
        "cost": "low", "latency": "low", "best_for": "routine extraction",
    }


def _cache_get(key: str) -> Optional[dict]:
    path = os.path.join(CACHE_DIR, key + ".json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return None


def _cache_put(key: str, value: dict) -> None:
    _ensure_dirs()
    with open(os.path.join(CACHE_DIR, key + ".json"), "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False)


def _save_decision(record: dict) -> None:
    _ensure_dirs()
    path = os.path.join(DECISIONS_DIR, f"{record['key']}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)


def llm_call(raw_text: str, decision: dict) -> Optional[dict]:
    """Call the selected provider. Returns parsed JSON dict or None.

    This is intentionally a thin wrapper with placeholders so it can be wired
    to a local runtime or OpenAI without changing the rest of the pipeline.
    """
    prompt = LLM_PROMPT_TEMPLATE.format(raw=raw_text)

    if decision["provider"] == "local":
        # Placeholder: load and run your local model at LOCAL_LLM_PATH here.
        # e.g. llama_cpp / ctransformers -> return json.loads(model(prompt))
        return None

    # OpenAI provider (optional dependency).
    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        return None
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    try:  # pragma: no cover - network dependent
        client = OpenAI()
        resp = client.chat.completions.create(
            model=decision["model"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return None


def extract(raw_text: str, base: Optional[dt.datetime] = None) -> dict:
    """Full extraction pipeline: heuristics first, cached LLM fallback if weak."""
    fields = heuristic_extract(raw_text, base)
    if fields["confidence"] >= 0.6:
        return fields

    key = _sha256(raw_text)
    cached = _cache_get(key)
    if cached:
        return {**fields, **{k: v for k, v in cached.items() if k in SCHEMA}}

    decision = select_model(raw_text, fields["confidence"])
    decision_record = {
        "key": key, "timestamp": _now_iso(), "heuristic_confidence": fields["confidence"],
        **decision,
    }
    _save_decision(decision_record)

    llm_fields = llm_call(raw_text, decision)
    if not llm_fields:
        return fields  # heuristics remain best-effort when LLM unavailable

    merged = {**fields, **{k: v for k, v in llm_fields.items() if k in SCHEMA}}
    merged["source"] = "cli"
    _cache_put(key, merged)
    return merged


# ----------------------------------------------------------------------------
# Storage: master CSV with schema evolution
# ----------------------------------------------------------------------------
def _read_master() -> tuple[list[str], list[dict]]:
    if not os.path.exists(MASTER_CSV):
        return list(SCHEMA), []
    with open(MASTER_CSV, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or list(SCHEMA)
        rows = [dict(r) for r in reader]
    return list(header), rows


def _write_master(header: list[str], rows: list[dict]) -> None:
    _ensure_dirs()
    with open(MASTER_CSV, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in header})


def evolve_schema(header: list[str], new_fields: list[str]) -> list[str]:
    """Append unseen fields and log the change. Backfill happens on write."""
    added = [f for f in new_fields if f not in header]
    if added:
        header = header + added
        _log_strategy(f"SCHEMA_EVOLVE added columns={added}")
    return header


def add_record(fields: dict) -> dict:
    header, rows = _read_master()
    header = evolve_schema(header, list(fields.keys()))
    next_id = 1 + max((int(r.get("id") or 0) for r in rows), default=0)
    record = {"id": next_id, **fields}
    rows.append(record)
    _write_master(header, rows)
    _split_records(record)
    return record


def _matches_identifier(row: dict, identifier: str) -> bool:
    """Match a row by exact id, ticket (case-insensitive), or text substring."""
    ident = identifier.strip()
    if ident.isdigit() and str(row.get("id")) == ident:
        return True
    ticket = (row.get("ticket") or "").lower()
    if ticket and ticket == ident.lower():
        return True
    haystack = f"{row.get('title') or ''} {row.get('raw_text') or ''}".lower()
    return len(ident) >= 3 and ident.lower() in haystack


def _current_occurrence_key(recurrence: Optional[str], today: dt.date) -> str:
    """Return a stable key identifying the current occurrence of a recurrence.

    Marking a recurring task "done for today" snoozes exactly this occurrence;
    the next occurrence produces a different key, so the reminder returns.
    """
    rec = (recurrence or "").lower()
    if rec == "daily" or not rec:
        return today.isoformat()
    if rec.startswith("weekly:"):
        target = WEEKDAYS.get(rec.split(":", 1)[1])
        if target is None:
            iso = today.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"
        monday = today - dt.timedelta(days=today.weekday())
        return (monday + dt.timedelta(days=target)).isoformat()
    if rec == "weekly":
        iso = today.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if rec == "monthly":
        return f"{today.year}-{today.month:02d}"
    return today.isoformat()


def mark_done(identifier: str, occurrence_only: bool = False) -> list[dict]:
    """Mark matching record(s) as done so they are skipped from reminders.

    Matches by numeric id, ticket, or a text substring. Returns updated rows.

    When occurrence_only is True, recurring tasks are only completed for the
    current occurrence (status stays open, last_done_occurrence is stamped) so
    the reminder returns at the next iteration. Non-recurring tasks are always
    completed permanently. Master CSV is the source of truth for session
    resume; part files are archival snapshots and left untouched.
    """
    header, rows = _read_master()
    header = evolve_schema(
        header, ["status", "completed_at", "last_done", "last_done_occurrence"]
    )
    today = dt.date.today()
    now = _now_iso()
    updated = [
        r for r in rows
        if _matches_identifier(r, identifier)
        and (r.get("status") or STATUS_OPEN) != STATUS_DONE
    ]
    for r in updated:
        recurring = bool(r.get("recurrence"))
        r["last_done"] = now
        r["last_done_occurrence"] = _current_occurrence_key(r.get("recurrence"), today)
        if occurrence_only and recurring:
            continue  # snooze this occurrence only; keep status open
        r["status"] = STATUS_DONE
        r["completed_at"] = now
    if updated:
        _write_master(header, rows)
        mode = "DONE_TODAY" if occurrence_only else "DONE"
        _log_strategy(
            f"{mode} identifier={identifier!r} ids={[r.get('id') for r in updated]}"
        )
    return updated


def restore_records(identifier: str) -> list[dict]:
    """Reopen matching done record(s) so they return to the active view.

    Matches by numeric id, ticket, or text substring. Clears status,
    completed_at, and the recurring snooze stamps (last_done,
    last_done_occurrence) so the task behaves as freshly active. Returns the
    restored rows.
    """
    header, rows = _read_master()
    restored = [
        r for r in rows
        if _matches_identifier(r, identifier)
        and (r.get("status") or STATUS_OPEN) == STATUS_DONE
    ]
    for r in restored:
        r["status"] = STATUS_OPEN
        r["completed_at"] = ""
        r["last_done"] = ""
        r["last_done_occurrence"] = ""
    if restored:
        _write_master(header, rows)
        _log_strategy(
            f"RESTORE identifier={identifier!r} ids={[r.get('id') for r in restored]}"
        )
    return restored


def delete_records(identifier: str) -> list[dict]:
    """Permanently remove matching record(s) from the master CSV.

    Matches by numeric id, ticket, or text substring (any status, including
    done). Returns the removed rows. The master CSV is the source of truth for
    the viewers and session resume; part files are archival snapshots and left
    untouched.
    """
    header, rows = _read_master()
    removed = [r for r in rows if _matches_identifier(r, identifier)]
    if removed:
        removed_ids = {str(r.get("id")) for r in removed}
        kept = [r for r in rows if str(r.get("id")) not in removed_ids]
        _write_master(header, kept)
        _log_strategy(
            f"DELETE identifier={identifier!r} ids={[r.get('id') for r in removed]}"
        )
    return removed


# ----------------------------------------------------------------------------
# Splitting strategy + adaptive learning
# ----------------------------------------------------------------------------
def _date_of(record: dict) -> str:
    ts = record.get("timestamp") or _now_iso()
    return ts[:10]


def _rows_for_date(rows: list[dict], date: str) -> list[dict]:
    return [r for r in rows if _date_of(r) == date]


def _split_records(record: dict) -> None:
    """Route a record into part files, adapting strategy on thresholds."""
    _ensure_dirs()
    _, rows = _read_master()
    date = _date_of(record)
    day_rows = _rows_for_date(rows, date)
    project = (record.get("project") or "misc")

    if len(day_rows) > DAILY_PROJECT_SHARD_THRESHOLD:
        # Strategy: project sharding within a per-date subfolder.
        day_dir = os.path.join(PARTS_DIR, date)
        os.makedirs(day_dir, exist_ok=True)
        part_path = os.path.join(day_dir, f"{_safe(project)}.csv")
        strategy = "date+project"
    else:
        # Strategy: date, 10 records per part.
        part_index = (len(day_rows) - 1) // RECORDS_PER_PART + 1
        part_path = os.path.join(PARTS_DIR, f"{date}_part{part_index}.csv")
        strategy = "date"

    _append_part(part_path, record)
    _maybe_log_strategy(date, strategy, len(day_rows))


_LAST_STRATEGY: dict[str, str] = {}


def _maybe_log_strategy(date: str, strategy: str, count: int) -> None:
    if _LAST_STRATEGY.get(date) != strategy:
        _LAST_STRATEGY[date] = strategy
        reason = (
            f"daily_rows={count} exceeded {DAILY_PROJECT_SHARD_THRESHOLD}"
            if strategy == "date+project"
            else f"daily_rows={count} within threshold"
        )
        _log_strategy(f"STRATEGY date={date} -> {strategy} ({reason})")


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def _append_part(path: str, record: dict) -> None:
    header, _ = _read_master()
    exists = os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow({k: record.get(k, "") for k in header})


# ----------------------------------------------------------------------------
# Session resume
# ----------------------------------------------------------------------------
URGENT_SET = {"urgent", "asap", "high"}


def _is_relevant(row: dict, today: str) -> bool:
    if (row.get("status") or STATUS_OPEN) == STATUS_DONE:
        return False  # permanently completed items are skipped
    recurrence = row.get("recurrence")
    recurring = bool(recurrence)
    if recurring:
        today_date = dt.date.fromisoformat(today)
        occ = _current_occurrence_key(recurrence, today_date)
        if (row.get("last_done_occurrence") or "") == occ:
            return False  # done for this iteration; returns next occurrence
    due_today = (row.get("due_date") or "")[:10] == today
    urgent = (row.get("urgency") or "").lower() in URGENT_SET
    return due_today or recurring or urgent


def session_summary(days: int = 0) -> list[dict]:
    _, rows = _read_master()
    today = dt.date.today().isoformat()
    if days > 0:
        cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        rows = [r for r in rows if _date_of(r) >= cutoff]
    return [r for r in rows if _is_relevant(r, today)]


def _how_to_do(row: dict) -> str:
    if row.get("assignee"):
        return f"assigned to {row['assignee']}"
    if row.get("impact"):
        return str(row["impact"])
    return "actionable: ask team"


def render_summary(rows: list[dict]) -> str:
    if not rows:
        return "Nothing due today, recurring, or urgent. You're clear."
    lines = ["Session resume — relevant items:", ""]
    for r in rows:
        what = r.get("title") or r.get("raw_text") or "(untitled)"
        when = r.get("due_date") or r.get("recurrence") or "n/a"
        urgency = r.get("urgency") or "normal"
        how = _how_to_do(r)
        impact = r.get("impact") or "n/a"
        lines.append(f"- [{r.get('id')}] {what}")
        lines.append(f"    when={when} | urgency={urgency} | how={how} | impact={impact}")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def cmd_note(text: str, due: Optional[str] = None) -> None:
    fields = extract(text)
    if due and due.strip():
        normalized = due.strip().replace("T", " ")
        parsed = parse_due_datetime(normalized) or parse_due_date(normalized)
        fields["due_date"] = parsed or due.strip()
    record = add_record(fields)
    print(json.dumps(record, ensure_ascii=False, indent=2))


def _read_text_arg(text: Optional[str], file: Optional[str]) -> str:
    """Resolve note text from a positional arg or a UTF-8 file.

    The ``--file`` path lets callers (e.g. the HTA viewer) hand over arbitrary
    text without shell-escaping quotes or special characters.
    """
    if file:
        with open(file, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    return (text or "").strip()


def cmd_start_session() -> None:
    print(render_summary(session_summary()))


def cmd_show(days: int) -> None:
    print(render_summary(session_summary(days)))


def cmd_migrate_schema() -> None:
    header, rows = _read_master()
    header = evolve_schema(header, list(SCHEMA))
    _write_master(header, rows)  # backfills missing columns with ""
    print(f"Schema OK. Columns: {header}")


def cmd_done(identifier: str, today_only: bool = False) -> None:
    updated = mark_done(identifier, occurrence_only=today_only)
    if not updated:
        print(f"No open item matched {identifier!r}.")
        return
    ids = ", ".join(str(r.get("id")) for r in updated)
    for r in updated:
        recurring = bool(r.get("recurrence"))
        label = r.get("title") or r.get("raw_text")
        if today_only and recurring:
            print(f"- [{r.get('id')}] {label}")
            print(f"    done for this occurrence ({r.get('recurrence')}); "
                  f"reminds again next iteration")
        else:
            print(f"- [{r.get('id')}] {label}  (done; skipped from reminders)")
    if not today_only:
        print(f"Marked done: {ids}")


def cmd_delete(identifier: str) -> None:
    removed = delete_records(identifier)
    if not removed:
        print(f"No item matched {identifier!r}.")
        return
    for r in removed:
        label = r.get("title") or r.get("raw_text")
        print(f"- [{r.get('id')}] {label}  (deleted permanently)")
    ids = ", ".join(str(r.get("id")) for r in removed)
    print(f"Deleted: {ids}")


def cmd_restore(identifier: str) -> None:
    restored = restore_records(identifier)
    if not restored:
        print(f"No done item matched {identifier!r}.")
        return
    for r in restored:
        label = r.get("title") or r.get("raw_text")
        print(f"- [{r.get('id')}] {label}  (restored to active)")
    ids = ", ".join(str(r.get("id")) for r in restored)
    print(f"Restored: {ids}")


def cmd_session_hook() -> None:
    """Emit a Copilot CLI sessionStart hook payload.

    Prints {"additionalContext": "..."} when relevant items exist so the
    assistant proactively reminds the user on every new/restarted/resumed
    session. Prints {} (no injection) when nothing is relevant.
    """
    rows = session_summary()
    if not rows:
        print("{}")
        return
    context = (
        "SESSION REMINDER (vna-assistance): the user has open tasks that are "
        "due today, recurring, or urgent. At the very start of your reply, "
        "greet the user and list these reminders. For each item show what, "
        "when, urgency, how-to-do, and impact. Items marked 'actionable: ask "
        "team' still need an owner. To complete one, run the vna-assistance "
        "'done' command.\n\n" + render_summary(rows)
    )
    print(json.dumps({"additionalContext": context}, ensure_ascii=True))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vna-assistance", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("note", help="add a note from free text")
    n.add_argument("text", nargs="?", help="the note text")
    n.add_argument("--file", help="read the note text from a UTF-8 file instead")
    n.add_argument("--due", help="explicit due date/time (ISO, e.g. 2026-09-05 "
                                 "or 2026-09-05T17:00); overrides any parsed date")
    sub.add_parser("start-session", help="show relevant items")
    s = sub.add_parser("show", help="show items from the last N days")
    s.add_argument("--days", type=int, default=7)
    d = sub.add_parser("done", help="mark a task done so it is skipped from reminders")
    d.add_argument("identifier", help="record id, ticket (e.g. MON-1122), or text substring")
    d.add_argument("--today", action="store_true",
                   help="for a recurring task, complete only this occurrence "
                        "(reminds again next iteration)")
    rm = sub.add_parser("delete", help="permanently remove a task from the master CSV")
    rm.add_argument("identifier", help="record id, ticket (e.g. MON-1122), or text substring")
    rs = sub.add_parser("restore", help="reopen a done task so it returns to the active view")
    rs.add_argument("identifier", help="record id, ticket (e.g. MON-1122), or text substring")
    sub.add_parser("migrate-schema", help="ensure master CSV has all columns")
    sub.add_parser("session-hook", help="emit sessionStart hook JSON (additionalContext)")
    sub.add_parser("selftest", help="run built-in unit tests")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "note":
        note_text = _read_text_arg(args.text, args.file)
        if not note_text:
            build_parser().error("note requires text or --file")
        cmd_note(note_text, getattr(args, "due", None))
    elif args.cmd == "start-session":
        cmd_start_session()
    elif args.cmd == "show":
        cmd_show(args.days)
    elif args.cmd == "done":
        cmd_done(args.identifier, today_only=args.today)
    elif args.cmd == "delete":
        cmd_delete(args.identifier)
    elif args.cmd == "restore":
        cmd_restore(args.identifier)
    elif args.cmd == "migrate-schema":
        cmd_migrate_schema()
    elif args.cmd == "session-hook":
        cmd_session_hook()
    elif args.cmd == "selftest":
        return run_selftest()
    return 0


# ----------------------------------------------------------------------------
# Unit tests (run: python vna-assistance-cli.py selftest)
# ----------------------------------------------------------------------------
def run_selftest() -> int:
    import unittest

    class ParsingTests(unittest.TestCase):
        BASE = dt.datetime(2025, 1, 6, 9, 0, 0)  # a Monday

        def test_example1_recurrence_task(self):
            txt = ("On every wednesday, I have to do the Monsoon morning duty, "
                   "and checking the production deployment "
                   "(assign to right person if possible)")
            f = heuristic_extract(txt, self.BASE)
            self.assertEqual(f["recurrence"], "weekly:wednesday")
            self.assertEqual(f["type"], "task")
            self.assertEqual(f["project"], "Monsoon")
            self.assertIsNone(f["assignee"])  # 'right person' is vague
            self.assertIn("production", (f["tags"] or ""))
            self.assertGreaterEqual(f["confidence"], 0.6)

        def test_example2_ticket_task(self):
            txt = ("On jira ticket MON-1122, need to ask other team how to "
                   "config env in PROD.")
            f = heuristic_extract(txt, self.BASE)
            self.assertEqual(f["ticket"], "MON-1122")
            self.assertEqual(f["project"], "MON")
            self.assertEqual(f["type"], "task")
            self.assertIn("prod", (f["tags"] or ""))
            self.assertGreaterEqual(f["confidence"], 0.6)

        def test_done_matching_and_skip(self):
            row = {"id": "5", "ticket": "MON-1122", "title": "config env",
                   "raw_text": "config env in PROD", "status": STATUS_OPEN}
            self.assertTrue(_matches_identifier(row, "5"))         # by id
            self.assertTrue(_matches_identifier(row, "mon-1122"))  # by ticket
            self.assertTrue(_matches_identifier(row, "config"))    # by text
            self.assertFalse(_matches_identifier(row, "999"))
            row["recurrence"] = "daily"
            self.assertTrue(_is_relevant(row, "2025-01-06"))
            row["status"] = STATUS_DONE
            self.assertFalse(_is_relevant(row, "2025-01-06"))  # done -> skipped

        def test_recurring_done_for_today_returns_next_iteration(self):
            # weekly:wednesday task; 2025-01-08 is a Wednesday.
            wed, next_wed, thu = "2025-01-08", "2025-01-15", "2025-01-09"
            row = {"id": "9", "recurrence": "weekly:wednesday", "status": STATUS_OPEN,
                   "last_done_occurrence": ""}
            self.assertTrue(_is_relevant(row, wed))  # relevant before completing
            occ = _current_occurrence_key("weekly:wednesday", dt.date.fromisoformat(wed))
            row["last_done_occurrence"] = occ
            self.assertEqual(row["status"], STATUS_OPEN)   # series stays open
            self.assertFalse(_is_relevant(row, wed))       # snoozed same day
            self.assertFalse(_is_relevant(row, thu))       # still snoozed this week
            self.assertTrue(_is_relevant(row, next_wed))   # reminds next iteration

        def test_daily_done_for_today_returns_tomorrow(self):
            row = {"id": "10", "recurrence": "daily", "status": STATUS_OPEN,
                   "last_done_occurrence": _current_occurrence_key(
                       "daily", dt.date.fromisoformat("2025-01-08"))}
            self.assertFalse(_is_relevant(row, "2025-01-08"))  # done today
            self.assertTrue(_is_relevant(row, "2025-01-09"))   # returns tomorrow

        def test_relative_due_dates_resolve_to_absolute(self):
            thu = dt.datetime(2026, 9, 3, 13, 0)  # a Thursday
            self.assertEqual(parse_due_date("finish next Monday", thu), "2026-09-07")
            self.assertEqual(parse_due_date("this friday demo", thu), "2026-09-04")
            self.assertEqual(parse_due_date("submit in 3 days", thu), "2026-09-06")
            self.assertEqual(parse_due_date("review in 2 weeks", thu), "2026-09-17")
            self.assertEqual(parse_due_date("plan next week", thu), "2026-09-07")
            self.assertEqual(parse_due_date("budget next month", thu), "2026-10-01")
            self.assertEqual(parse_due_date("deadline 07/09/2026", thu), "2026-09-07")
            self.assertEqual(parse_due_date("release 2026-11-01", thu), "2026-11-01")
            self.assertIsNone(parse_due_date("just a plain note", thu))

        def test_due_datetime_includes_time(self):
            thu = dt.datetime(2026, 9, 3, 13, 0)  # Thursday 13:00
            # date + time
            self.assertEqual(
                parse_due_datetime("finish next Monday at 5pm", thu), "2026-09-07T17:00")
            self.assertEqual(
                parse_due_datetime("call today 09:30", thu), "2026-09-03T09:30")
            self.assertEqual(
                parse_due_datetime("demo tomorrow noon", thu), "2026-09-04T12:00")
            # date only -> unchanged (no time component)
            self.assertEqual(parse_due_datetime("finish next Monday", thu), "2026-09-07")
            # time only, still upcoming today
            self.assertEqual(parse_due_datetime("standup at 3pm", thu), "2026-09-03T15:00")
            # time only, already past -> rolls to tomorrow
            self.assertEqual(parse_due_datetime("ping at 9am", thu), "2026-09-04T09:00")
            # no time signal
            self.assertIsNone(parse_time_of_day("review MON-1122 in 3 days"))
            self.assertEqual(parse_time_of_day("meet at 14:45"), (14, 45))
            self.assertEqual(parse_time_of_day("lunch at 12pm"), (12, 0))
            self.assertEqual(parse_time_of_day("wake 12am"), (0, 0))

    suite = unittest.TestLoader().loadTestsFromTestCase(ParsingTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
