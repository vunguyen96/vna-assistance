// vna-assistance · Today's tasks — dependency-free CSV viewer.
// Mirrors the relevance + occurrence rules from vna-assistance-cli.py so the
// browser shows exactly what `start-session` would remind you about.

const SCHEMA = [
  "id", "timestamp", "title", "type", "ticket", "recurrence", "due_date",
  "urgency", "impact", "project", "assignee", "tags", "raw_text", "source",
  "confidence", "status", "completed_at", "last_done", "last_done_occurrence",
];

const STATUS_DONE = "done";
const URGENT_SET = new Set(["urgent", "asap", "high"]);
const WEEKDAYS = {
  monday: 0, tuesday: 1, wednesday: 2, thursday: 3,
  friday: 4, saturday: 5, sunday: 6,
};

// --- CSV parsing (RFC-4180-ish: quoted fields, "" escapes, CRLF/CR/LF) -------

const parseCsv = (text) => {
  const { rows, field, row, quoted } = Array.from(text).reduce((s, ch, i, arr) => {
    if (s.quoted) {
      if (ch === '"') {
        if (arr[i + 1] === '"') { s.field += '"'; s.skip = true; return s; }
        s.quoted = false;
        return s;
      }
      if (s.skip) { s.skip = false; return s; }
      s.field += ch;
      return s;
    }
    if (s.skip) { s.skip = false; return s; }
    if (ch === '"') { s.quoted = true; return s; }
    if (ch === ",") { s.row.push(s.field); s.field = ""; return s; }
    if (ch === "\r") { return s; }
    if (ch === "\n") { s.row.push(s.field); s.rows.push(s.row); s.row = []; s.field = ""; return s; }
    s.field += ch;
    return s;
  }, { rows: [], row: [], field: "", quoted: false, skip: false });

  const tail = [...row, field];
  const hasTail = field !== "" || row.length > 0;
  return hasTail ? [...rows, tail] : rows;
};

const toObjects = (matrix) => {
  const nonEmpty = matrix.filter((r) => r.some((c) => c.trim() !== ""));
  if (nonEmpty.length === 0) return [];
  const [header, ...body] = nonEmpty;
  return body.map((cells) =>
    Object.fromEntries(header.map((key, i) => [key, cells[i] ?? ""])));
};

// --- Occurrence + relevance (ports of the Python helpers) --------------------

// Local calendar date (YYYY-MM-DD) — matches Python's date.isoformat().
// Avoid toISOString(), which converts to UTC and can shift the day.
const iso = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

const isoWeek = (d) => {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((date - yearStart) / 86400000 + 1) / 7);
  return `${date.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
};

const currentOccurrenceKey = (recurrence, today) => {
  const rec = (recurrence || "").toLowerCase();
  if (rec === "daily" || rec === "") return iso(today);
  if (rec.startsWith("weekly:")) {
    const target = WEEKDAYS[rec.split(":", 2)[1]];
    if (target === undefined) return isoWeek(today);
    const mondayOffset = (today.getDay() + 6) % 7; // Mon=0 like Python weekday()
    const monday = new Date(today);
    monday.setDate(today.getDate() - mondayOffset + target);
    return iso(monday);
  }
  if (rec === "weekly") return isoWeek(today);
  if (rec === "monthly") return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  return iso(today);
};

// Visible = every actionable task now or in the future: not done, not snoozed
// for its current occurrence, and either recurring, urgent, or carrying a due
// date (today, overdue, or future).
const isVisible = (row, today) => {
  if ((row.status || "open") === STATUS_DONE) return false;
  const recurring = Boolean(row.recurrence);
  if (recurring) {
    const occ = currentOccurrenceKey(row.recurrence, today);
    if ((row.last_done_occurrence || "") === occ) return false;
  }
  const hasDue = Boolean((row.due_date || "").slice(0, 10));
  const urgent = URGENT_SET.has((row.urgency || "").toLowerCase());
  return recurring || urgent || hasDue;
};

// A task belongs to "today" (top of the list) when it is due today or overdue,
// urgent, or a recurring occurrence that lands on today.
const isToday = (row, today) => {
  const key = iso(today);
  const due = (row.due_date || "").slice(0, 10);
  if (due && due <= key) return true;
  if (URGENT_SET.has((row.urgency || "").toLowerCase())) return true;
  if (row.recurrence) return currentOccurrenceKey(row.recurrence, today) === key;
  return false;
};

// Next date on/after today for a recurring token, used to order upcoming items.
const nextRecurringDate = (recurrence, today) => {
  const rec = (recurrence || "").toLowerCase();
  if (rec.startsWith("weekly:")) {
    const target = WEEKDAYS[rec.split(":", 2)[1]];
    if (target !== undefined) {
      const offset = (today.getDay() + 6) % 7;
      const d = new Date(today);
      d.setDate(today.getDate() - offset + target);
      if (iso(d) < iso(today)) d.setDate(d.getDate() + 7);
      return d;
    }
  }
  return new Date(today); // daily / weekly / monthly / unknown -> this period
};

// A comparable date string driving chronological ordering.
const effectiveDate = (row, today) => {
  const due = (row.due_date || "").slice(0, 10);
  if (due) return due;
  if (row.recurrence) return iso(nextRecurringDate(row.recurrence, today));
  return "9999-12-31";
};

const howToDo = (row) =>
  row.assignee ? `assigned to ${row.assignee}`
    : row.impact ? String(row.impact)
      : { ask: true, text: "actionable: ask team" };

// --- Rendering ---------------------------------------------------------------

const urgencyClass = (u) => {
  const v = (u || "").toLowerCase();
  if (v === "urgent" || v === "asap") return "urgent";
  if (v === "high") return "high";
  return "normal";
};

const urgencyRank = (u) => {
  const v = (u || "").toLowerCase();
  if (v === "urgent" || v === "asap") return 0;
  if (v === "high") return 1;
  return 2;
};

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

const metaRow = (label, value, cls) => {
  const dt = el("dt", null, label);
  const dd = el("dd", cls, value);
  return [dt, dd];
};

const renderCard = (row, today) => {
  const li = el("li", `card u-${urgencyClass(row.urgency)}${today ? " is-today" : ""}`);
  li.appendChild(el("h3", null, row.title || row.raw_text || "(untitled)"));

  const badges = el("div", "badges");
  if (today) badges.appendChild(el("span", "badge today", "TODAY"));
  const type = row.type || "note";
  badges.appendChild(el("span", "badge", type));
  if (row.urgency) badges.appendChild(el("span", `badge ${urgencyClass(row.urgency)}`, row.urgency));
  if (row.ticket) badges.appendChild(el("span", "badge", row.ticket));
  if (row.project) badges.appendChild(el("span", "badge", row.project));
  li.appendChild(badges);

  const meta = el("dl", "meta");
  const when = row.due_date || row.recurrence || "n/a";
  const how = howToDo(row);
  const rows = [
    metaRow("When", when),
    metaRow("Impact", row.impact || "n/a"),
    typeof how === "string"
      ? metaRow("How", how)
      : metaRow("How", how.text, "ask"),
  ];
  rows.flat().forEach((n) => meta.appendChild(n));
  li.appendChild(meta);
  return li;
};

const listEl = document.getElementById("list");
const statusEl = document.getElementById("status");
const subtitleEl = document.getElementById("subtitle");
const dropzone = document.getElementById("dropzone");

const setStatus = (msg, isError = false) => {
  statusEl.textContent = msg;
  statusEl.classList.toggle("error", isError);
};

const render = (rows) => {
  const today = new Date();
  const visible = rows.filter((r) => isVisible(r, today));

  const todayTasks = visible
    .filter((r) => isToday(r, today))
    .sort((a, b) =>
      urgencyRank(a.urgency) - urgencyRank(b.urgency) ||
      effectiveDate(a, today).localeCompare(effectiveDate(b, today)));

  const upcoming = visible
    .filter((r) => !isToday(r, today))
    .sort((a, b) =>
      effectiveDate(a, today).localeCompare(effectiveDate(b, today)) ||
      urgencyRank(a.urgency) - urgencyRank(b.urgency));

  listEl.replaceChildren();
  subtitleEl.textContent =
    `${iso(today)} · ${todayTasks.length} today · ${upcoming.length} upcoming · ${rows.length} total`;

  if (visible.length === 0) {
    listEl.appendChild(el("li", "empty",
      "No tasks due, recurring, or upcoming. You're clear."));
    return;
  }

  const addGroup = (label, items, cls) => {
    if (items.length === 0) return;
    listEl.appendChild(el("li", `group ${cls}`, label));
    items
      .map((r) => renderCard(r, cls === "today"))
      .forEach((card) => listEl.appendChild(card));
  };

  addGroup(`Today (${todayTasks.length})`, todayTasks, "today");
  addGroup(`Upcoming (${upcoming.length})`, upcoming, "upcoming");
};

const loadText = (text, sourceLabel) => {
  try {
    const rows = toObjects(parseCsv(text));
    dropzone.classList.add("hidden");
    setStatus(`Loaded ${rows.length} records from ${sourceLabel}.`);
    render(rows);
  } catch (err) {
    setStatus(`Failed to parse CSV: ${err.message}`, true);
  }
};

const readFile = (file) => {
  const reader = new FileReader();
  reader.onload = () => loadText(String(reader.result), file.name);
  reader.onerror = () => setStatus("Could not read the selected file.", true);
  reader.readAsText(file);
};

// --- Wiring: auto-fetch (when served/next to CSV), file input, drag & drop ----

let lastFile = null;

document.getElementById("fileInput").addEventListener("change", (e) => {
  const [file] = e.target.files;
  if (file) { lastFile = file; readFile(file); }
});

document.getElementById("refreshBtn").addEventListener("click", () => {
  if (lastFile) return readFile(lastFile);
  tryAutoLoad();
});

["dragenter", "dragover"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.add("drag");
  }));

["dragleave", "drop"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag");
  }));

dropzone.addEventListener("drop", (e) => {
  const [file] = e.dataTransfer.files;
  if (file) { lastFile = file; readFile(file); }
});

// CSV location tried automatically when the page opens. When the page is served
// from the data folder (see serve.cmd) or sits next to the CSV, the relative
// path just works. To read a store elsewhere via file:// (Firefox only; Chrome
// blocks file:// reads, so the picker is the fallback), set an absolute path
// below, e.g. "C:\\Users\\me\\vna-assistance\\vna-assistance.csv".
const DEFAULT_CSV_PATH = "";
const DEFAULT_CSV_URL = DEFAULT_CSV_PATH
  ? `file:///${DEFAULT_CSV_PATH.replace(/\\/g, "/")}`
  : "";

const tryAutoLoad = async () => {
  const candidates = ["vna-assistance.csv", DEFAULT_CSV_URL].filter(Boolean);
  const attempt = async (url) => {
    const res = await fetch(url, { cache: "no-store" });
    // file:// responses report status 0 but still expose the body.
    if (!res.ok && res.status !== 0) throw new Error(String(res.status));
    const text = await res.text();
    if (!text.trim()) throw new Error("empty");
    return text;
  };
  const loaded = await candidates.reduce(async (prev, url) => {
    if (await prev) return true;
    try {
      loadText(await attempt(url), url === "vna-assistance.csv" ? url : DEFAULT_CSV_PATH);
      return true;
    } catch {
      return false;
    }
  }, Promise.resolve(false));

  if (!loaded) {
    setStatus(
      "Couldn't auto-read the CSV (your browser blocks local file access). " +
      "Click \u201cOpen CSV\u2026\u201d or drag vna-assistance.csv here.");
  }
};

tryAutoLoad();
