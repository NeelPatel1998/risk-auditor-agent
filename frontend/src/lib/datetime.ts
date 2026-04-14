/**
 * Parse timestamps from the API or SQLite: naive UTC `YYYY-MM-DD HH:MM:SS`, or ISO with Z / offset.
 * Without a timezone, JS treats `YYYY-MM-DD HH:MM:SS` as *local*, which skews sidebar times.
 */
export function parseStoredUtc(isoOrSqlite: string): Date {
  const t = (isoOrSqlite || '').trim()
  if (!t) return new Date(NaN)
  if (/[zZ]$/.test(t)) return new Date(t)
  if (/[+-]\d{2}:?\d{2}$/.test(t)) return new Date(t)
  const core = t.includes('T') ? t : t.replace(' ', 'T')
  return new Date(core.endsWith('Z') ? core : `${core}Z`)
}
