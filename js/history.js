import { fetchHistory } from './app.js'
import { getDisplayLevel } from './theme.js'

const $ = (sel) => document.querySelector(sel)

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

export async function loadHistoryPage() {
  $('#historyStatus').textContent = '加载中…'
  $('#historyStatus').className = 'status-bar'
  try {
    const data = await fetchHistory(30)
    const list = (data && data.list) || data || []
    renderList(Array.isArray(list) ? list : [])
    $('#historyStatus').textContent = `共 ${Array.isArray(list) ? list.length : 0} 条记录`
    $('#historyStatus').className = 'status-bar ok'
  } catch (err) {
    $('#historyStatus').textContent = err?.message || '加载失败'
    $('#historyStatus').className = 'status-bar err'
  }
}

export function initHistoryPage() {
  $('#refreshBtn')?.addEventListener('click', () => loadHistoryPage())
  loadHistoryPage()
}
