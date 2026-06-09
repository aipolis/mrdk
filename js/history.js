import { fetchHistory } from './api.js?v=20260609c'
import { getDisplayLevel } from './theme.js?v=20260609c'
import { createTrendController } from './trendDraw.js'
import { beijingParts } from './time.js?v=20260609a'

const $ = (sel) => document.querySelector(sel)

// ── 月历 ──────────────────────────────────────────────
function scoreColor(s) {
  s = Number(s) || 0
  if (s >= 90) return '#820014'
  if (s >= 75) return '#cf1322'
  if (s >= 60) return '#ff4d4f'
  if (s >= 50) return '#faad14'
  if (s >= 40) return '#52c41a'
  if (s >= 30) return '#38bdf8'
  return '#94a3b8'
}

let calYear = 0, calMonth = 0, calList = []

function buildCalCells(list, year, month) {
  const pad = n => String(n).padStart(2, '0')
  const dateMap = {}
  for (const item of list || []) {
    const d = String(item.date || '')
    if (/^\d{4}-\d{2}-\d{2}$/.test(d)) dateMap[d] = item
  }
  const daysInMonth = new Date(year, month, 0).getDate()
  const startWd = new Date(year, month - 1, 1).getDay()
  const today = beijingParts()
  const todayStr = `${today.year}-${pad(today.month)}-${pad(today.day)}`
  const cells = []
  for (let i = 0; i < startWd; i++) cells.push(null)
  for (let d = 1; d <= daysInMonth; d++) {
    const ds = `${year}-${pad(month)}-${pad(d)}`
    const item = dateMap[ds]
    cells.push({ day: d, isToday: ds === todayStr, item })
  }
  while (cells.length % 7 !== 0) cells.push(null)
  return cells
}

function renderCalendar() {
  const grid = $('#calGrid'), title = $('#calTitle')
  if (!grid || !title) return
  title.textContent = `${calYear}年${calMonth}月`
  const cells = buildCalCells(calList, calYear, calMonth)
  grid.innerHTML = cells.map(cell => {
    if (!cell) return '<div class="cal-cell cal-cell-empty"></div>'
    if (cell.item) {
      const c = scoreColor(cell.item.score)
      return `<div class="cal-cell" style="background:${c}">
        <span class="cal-score">${cell.item.score}</span>
        <span class="cal-day-num">${cell.day}</span>
      </div>`
    }
    const todayCls = cell.isToday ? ' cal-cell-today' : ''
    return `<div class="cal-cell cal-cell-nodata${todayCls}">
      <span class="cal-day-num-only">${cell.day}</span>
    </div>`
  }).join('')
}

let calInited = false

function initCalendar(list) {
  calList = list
  if (!calYear) {
    const now = beijingParts()
    calYear = now.year; calMonth = now.month
  }
  renderCalendar()
  if (calInited) return
  calInited = true
  $('#calPrev')?.addEventListener('click', () => {
    calMonth--; if (calMonth < 1) { calMonth = 12; calYear-- }
    renderCalendar()
  })
  $('#calNext')?.addEventListener('click', () => {
    const now = beijingParts()
    if (calYear >= now.year && calMonth >= now.month) return
    calMonth++; if (calMonth > 12) { calMonth = 1; calYear++ }
    renderCalendar()
  })
}

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function formatIndexChg(item) {
  if (item.indexChgText != null && item.indexChgText !== '') {
    return String(item.indexChgText)
  }
  if (item.indexChg == null || item.indexChg === '') return '--'
  const n = Number(item.indexChg)
  if (Number.isNaN(n)) return '--'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

function indexChgClass(item) {
  if (item.indexChg == null && !item.indexChgText) return ''
  const up = item.indexUp != null ? item.indexUp : Number(item.indexChg) >= 0
  return up ? 'index-up' : 'index-down'
}

function renderList(list) {
  const tbody = $('#historyBody')
  if (!tbody) return
  if (!list?.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty">暂无历史数据</td></tr>'
    return
  }
  tbody.innerHTML = list.map((item) => {
    const level = getDisplayLevel(item.score)
    const idxCls = indexChgClass(item)
    return `
      <tr>
        <td>${esc(item.date)}</td>
        <td class="score ${level.class}">${esc(item.score)}</td>
        <td class="level ${level.class}">${esc(item.level || level.label)}</td>
        <td class="index-chg ${idxCls}">${esc(formatIndexChg(item))}</td>
      </tr>
    `
  }).join('')
}

let trendCtrl = null

function initTrendController() {
  if (trendCtrl) return trendCtrl
  trendCtrl = createTrendController({
    canvas: $('#trendCanvas'),
    titleEl: $('#trendTitle'),
    periodRoot: $('#trendPeriods'),
    defaultDays: 10,
  })
  return trendCtrl
}

export async function loadHistoryPage() {
  $('#historyStatus').textContent = '加载中…'
  $('#historyStatus').className = 'status-bar'
  try {
    const data = await fetchHistory(30)
    const list = (data && data.list) || data || []
    const rows = Array.isArray(list) ? list : []
    renderList(rows)
    initTrendController().setHistoryList(rows)
    initCalendar(rows)
    $('#historyStatus').textContent = `共 ${rows.length} 条记录`
    $('#historyStatus').className = 'status-bar ok'
  } catch (err) {
    $('#historyStatus').textContent = err?.message || '加载失败'
    $('#historyStatus').className = 'status-bar err'
  }
}

export function initHistoryPage() {
  initTrendController()
  $('#refreshBtn')?.addEventListener('click', () => loadHistoryPage())
  window.addEventListener('resize', () => trendCtrl?.render())
  loadHistoryPage()
}
