#!/usr/bin/env node
// vna-assistance · print today's tasks by reading the CSV file directly.
// No service, no dependencies. Mirrors the CLI relevance/occurrence rules.
//
//   node open-today.mjs
//

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

const STATUS_DONE = "done";
const URGENT_SET = new Set(["urgent", "asap", "high"]);
const WEEKDAYS = {
  monday: 0, tuesday: 1, wednesday: 2, thursday: 3,
  friday: 4, saturday: 5, sunday: 6,
};

// Default store location: <user home>\vna-assistance. Override with VNA_HOME.
const DEFAULT_HOME = process.env.VNA_HOME || join(homedir(), "vna-assistance");

const csvPath = () => join(DEFAULT_HOME, "vna-assistance.csv");

const parseCsv = (text) => {
  const state = { rows: [], row: [], field: "", quoted: false, skip: false };
  Array.from(text).forEach((ch, i, arr) => {
    if (state.quoted) {
      if (ch === '"') {
        if (arr[i + 1] === '"') { state.field += '"'; state.skip = true; return; }
        state.quoted = false; return;
      }
      if (state.skip) { state.skip = false; return; }
      state.field += ch; return;
    }
    if (state.skip) { state.skip = false; return; }
    if (ch === '"') { state.quoted = true; return; }
    if (ch === ",") { state.row.push(state.field); state.field = ""; return; }
    if (ch === "\r") return;
    if (ch === "\n") { state.row.push(state.field); state.rows.push(state.row); state.row = []; state.field = ""; return; }
    state.field += ch;
  });
  if (state.field !== "" || state.row.length > 0) state.rows.push([...state.row, state.field]);
  return state.rows;
};

const toObjects = (matrix) => {
  const nonEmpty = matrix.filter((r) => r.some((c) => c.trim() !== ""));
  if (nonEmpty.length === 0) return [];
  const [header, ...body] = nonEmpty;
  return body.map((cells) =>
    Object.fromEntries(header.map((key, i) => [key, cells[i] ?? ""])));
};

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
    const mondayOffset = (today.getDay() + 6) % 7;
    const monday = new Date(today);
    monday.setDate(today.getDate() - mondayOffset + target);
    return iso(monday);
  }
  if (rec === "weekly") return isoWeek(today);
  if (rec === "monthly") return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  return iso(today);
};

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

const isToday = (row, today) => {
  const key = iso(today);
  const due = (row.due_date || "").slice(0, 10);
  if (due && due <= key) return true;
  if (URGENT_SET.has((row.urgency || "").toLowerCase())) return true;
  if (row.recurrence) return currentOccurrenceKey(row.recurrence, today) === key;
  return false;
};

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
  return new Date(today);
};

const effectiveDate = (row, today) => {
  const due = (row.due_date || "").slice(0, 10);
  if (due) return due;
  if (row.recurrence) return iso(nextRecurringDate(row.recurrence, today));
  return "9999-12-31";
};

const howToDo = (row) =>
  row.assignee ? `assigned to ${row.assignee}`
    : row.impact ? String(row.impact)
      : "actionable: ask team";

const rankOf = (u) => {
  const v = (u || "").toLowerCase();
  if (v === "urgent" || v === "asap") return 0;
  if (v === "high") return 1;
  return 2;
};

const printItem = (r) => {
  const what = r.title || r.raw_text || "(untitled)";
  const when = r.due_date || r.recurrence || "n/a";
  const urgency = r.urgency || "normal";
  console.log(`- [${r.id}] ${what}`);
  console.log(`    when=${when} | urgency=${urgency} | how=${howToDo(r)} | impact=${r.impact || "n/a"}`);
};

const main = () => {
  const path = csvPath();
  const today = new Date();
  let text;
  try {
    text = readFileSync(path, "utf8");
  } catch {
    console.error(`No CSV found at ${path}. Add a note first with the CLI.`);
    process.exit(1);
  }
  const rows = toObjects(parseCsv(text));
  const visible = rows.filter((r) => isVisible(r, today));

  const todayTasks = visible
    .filter((r) => isToday(r, today))
    .sort((a, b) =>
      rankOf(a.urgency) - rankOf(b.urgency) ||
      effectiveDate(a, today).localeCompare(effectiveDate(b, today)));

  const upcoming = visible
    .filter((r) => !isToday(r, today))
    .sort((a, b) =>
      effectiveDate(a, today).localeCompare(effectiveDate(b, today)) ||
      rankOf(a.urgency) - rankOf(b.urgency));

  console.log(`Tasks (${iso(today)}) — ${todayTasks.length} today, ${upcoming.length} upcoming, ${rows.length} total\n`);
  if (visible.length === 0) {
    console.log("No tasks due, recurring, or upcoming. You're clear.");
    return;
  }
  if (todayTasks.length > 0) {
    console.log(`== Today (${todayTasks.length}) ==`);
    todayTasks.forEach(printItem);
  }
  if (upcoming.length > 0) {
    console.log(`${todayTasks.length > 0 ? "\n" : ""}== Upcoming (${upcoming.length}) ==`);
    upcoming.forEach(printItem);
  }
};

main();
