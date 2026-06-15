// LSE trading hours helpers — shared by Sidebar and any polling component.
//
// Regular hours: 08:00–16:30 London, Mon–Fri, excluding England & Wales bank
// holidays. Christmas Eve and New Year's Eve are half-days (12:30 close) when
// they fall on a weekday. Update UK_HOLIDAYS / UK_HALF_DAYS annually.

const UK_HOLIDAYS = new Set([
  // 2026
  '2026-01-01', '2026-04-03', '2026-04-06', '2026-05-04', '2026-05-25',
  '2026-08-31', '2026-12-25', '2026-12-28',
  // 2027
  '2027-01-01', '2027-03-26', '2027-03-29', '2027-05-03', '2027-05-31',
  '2027-08-30', '2027-12-27', '2027-12-28',
]);

const UK_HALF_DAYS = new Set([
  '2026-12-24', '2026-12-31',
  '2027-12-24', '2027-12-31',
]);

const LSE_OPEN_SEC       = 8 * 3600;
const LSE_CLOSE_SEC      = 16 * 3600 + 30 * 60;
const LSE_HALF_CLOSE_SEC = 12 * 3600 + 30 * 60;

const WEEKDAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function londonParts(date = new Date()) {
  const fmt = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/London',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false, weekday: 'short',
  });
  const p: Record<string, string> = {};
  for (const part of fmt.formatToParts(date)) p[part.type] = part.value;
  return p;
}

function isLseTradingDay(iso: string, weekday: string) {
  if (weekday === 'Sat' || weekday === 'Sun') return false;
  return !UK_HOLIDAYS.has(iso);
}

export function nextOpenLabel(year: number, month: number, day: number) {
  const d = new Date(Date.UTC(year, month - 1, day, 12));
  for (let i = 0; i < 14; i++) {
    d.setUTCDate(d.getUTCDate() + 1);
    const wd = d.getUTCDay();
    const iso = d.toISOString().slice(0, 10);
    if (wd !== 0 && wd !== 6 && !UK_HOLIDAYS.has(iso)) {
      return `Opens ${WEEKDAY_NAMES[wd]} 08:00`;
    }
  }
  return 'Closed';
}

export type LseStatus =
  | { open: true;  secondsToClose: number }
  | { open: false; nextOpen: string };

export function lseStatus(): LseStatus {
  const p = londonParts();
  let hour = parseInt(p.hour, 10);
  if (hour === 24) hour = 0;
  const secNow   = hour * 3600 + parseInt(p.minute, 10) * 60 + parseInt(p.second, 10);
  const iso      = `${p.year}-${p.month}-${p.day}`;
  const trading  = isLseTradingDay(iso, p.weekday);
  const closeSec = UK_HALF_DAYS.has(iso) ? LSE_HALF_CLOSE_SEC : LSE_CLOSE_SEC;

  if (trading && secNow >= LSE_OPEN_SEC && secNow < closeSec) {
    return { open: true, secondsToClose: closeSec - secNow };
  }
  if (trading && secNow < LSE_OPEN_SEC) {
    return { open: false, nextOpen: 'Opens today 08:00' };
  }
  return {
    open: false,
    nextOpen: nextOpenLabel(
      parseInt(p.year, 10),
      parseInt(p.month, 10),
      parseInt(p.day, 10),
    ),
  };
}
