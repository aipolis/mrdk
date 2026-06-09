const BJT_OFFSET_MS = 8 * 60 * 60 * 1000

export function beijingParts(now = new Date()) {
  const bj = new Date(now.getTime() + BJT_OFFSET_MS)
  return {
    year: bj.getUTCFullYear(),
    month: bj.getUTCMonth() + 1,
    day: bj.getUTCDate(),
    weekday: bj.getUTCDay(),
    hour: bj.getUTCHours(),
    minute: bj.getUTCMinutes(),
    hm: bj.getUTCHours() * 60 + bj.getUTCMinutes(),
  }
}

export function beijingDateKey(now = new Date()) {
  const p = beijingParts(now)
  return `${p.year}${String(p.month).padStart(2, '0')}${String(p.day).padStart(2, '0')}`
}
