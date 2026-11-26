/**
 * Server-date-aware day formatting.
 * Always compares against authoritative server `today` and `tomorrow` ISO strings
 * to eliminate UTC vs local timezone mismatches around midnight.
 */
export function formatDayLabel(isoDate: string, todayIso: string, tomorrowIso: string): string {
  if (todayIso && isoDate === todayIso) return 'Today';
  if (tomorrowIso && isoDate === tomorrowIso) return 'Tmrw';
  return isoDate.slice(5);
}
