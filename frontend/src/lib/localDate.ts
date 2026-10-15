// Dates as the person at the screen reads them. `toISOString()` is UTC, so
// slicing it gives the wrong day for seven hours of every WIB day (00:00–06:59
// is still "yesterday" in UTC) — and, for a midnight date, always the day before.

const pad = (n: number) => String(n).padStart(2, "0");

/** YYYY-MM-DD of `d` in the viewer's own timezone. */
export function localDay(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** HH:MM of `d` in the viewer's own timezone. */
export function localTime(d: Date): string {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
