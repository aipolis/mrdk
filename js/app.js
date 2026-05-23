import { API_BASE, FETCH_TIMEOUT_MS, AUTO_REFRESH_MS } from './config.js'
import { drawSteeringGauge } from './gaugeDraw.js'
import { getDisplayLevel, dailyQuote, formatHeaderDate } from './theme.js'
import { normalizeSections } from './indicators.js'

const $ = (sel) => document.querySelector(sel)

async function fetchJson(path) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS)
  try {
    const res = await fetch(`${API_BASE.replace(/\/$/, '')}${path}`, {
      signal: ctrl.signal,
      headers: { Accept: 'application/json' },
    })
    const json = await res.json()
    if (json.code === 2 && /预热/.test(json.message || '')) {
      const err = new Error(json.message || '缓存预热中')
      err.warming = true
      throw err
    }
    if (json.code !== 0) throw new Error(json.message || `请求失败 ${res.status}`)
    return json.data
  } finally {
    clearTimeout(timer)
  }
}

export function fetchToday() {
  return fetchJson('/api/sentiment/today')
}

export function fetchHistory(days = 30) {
  return fetchJson(`/api/sentiment/history?days=${days}&tab=day`)
}

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function setupGaugeCanvas(canvas, score) {
  if (!canvas) return
  const dpr = window.devicePixelRatio || 1
  const rect = canvas.getBoundingClientRect()
  canvas.width = Math.round(rect.width * dpr)
  canvas.height = Math.round(rect.height * dpr)
  const ctx = canvas.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  drawSteeringGauge(ctx, rect.width, rect.height, score, 'dark')
}

function renderPeripheral(items) {
  const cells = (items || []).map((cell) => `
    <article class="peripheral-cell">
      <span class="peripheral-label">${esc(cell.label)}</span>
      <span class="peripheral-price">${esc(cell.price || cell.value || '--')}</span>
      <span class="peripheral-chg ${cell.up ? 'up' : cell.trend === 'down' ? 'down' : ''}">${esc(cell.chgText || '--')}</span>
    </article>
  `).join('')
  return `<section class="peripheral-row">${cells}</section>`
}

function renderGridSection(section) {
  if (section.layout === 'row3' && section.items?.length) {
    return renderPeripheral(section.items)
  }

  const rows = section.rows || []
  if (!rows.length) {
    if (section.pending) return '<p class="grid-empty">9:30 开盘后实时更新</p>'
    return '<p class="grid-empty">暂无数据</p>'
  }

  const prefix = section.id === 'yesterday' ? '前 ' : '昨 '
  let html = '<section class="grid9">'
  for (const row of rows) {
    html += '<section class="grid9-row">'
    for (const cell of row) {
      const arrow = cell.trendArrow || ''
      const good = cell.trendGood !== false
      const prev = cell.prev && cell.prev !== '--'
        ? `<span class="grid9-sub"><span class="grid9-sub-prefix">${prefix}</span><span class="grid9-sub-val">${esc(cell.prev)}</span></span>`
        : '<span class="grid9-sub grid9-sub--empty"></span>'
      html += `
        <article class="grid9-cell">
          <span class="grid9-value-row">
            <span class="grid9-value">${esc(cell.displayValue || cell.value || '--')}</span>
            ${arrow ? `<span class="trend-arrow ${good ? 'trend-good' : 'trend-bad'}">${arrow}</span>` : ''}
          </span>
          <span class="grid9-label">${esc(cell.label)}</span>
          ${prev}
        </article>
      `
    }
    html += '</section>'
  }
  html += '</section>'
  return html
}

function renderSections(sections) {
  const box = $('#sections')
  if (!box) return
  if (!sections?.length) {
    box.innerHTML = '<p class="grid-empty">暂无指标数据</p>'
    return
  }
  box.innerHTML = sections.map((sec) => `
    <section class="section">
      <header class="section-head">
        <h2 class="section-title">${esc(sec.title)}</h2>
        <span class="section-meta">${esc(sec.meta || '')}</span>
      </header>
      <article class="card section-card">${renderGridSection(sec)}</article>
    </section>
  `).join('')
}

function drawTrend(canvas, trend) {
  if (!canvas) return
  window.__lastTrend = trend || []
  if (!trend?.length) return

  const dpr = window.devicePixelRatio || 1
  const rect = canvas.getBoundingClientRect()
  canvas.width = Math.round(rect.width * dpr)
  canvas.height = Math.round(rect.height * dpr)
  const ctx = canvas.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  const w = rect.width
  const h = rect.height
  ctx.clearRect(0, 0, w, h)

  const padL = 28
  const padR = 12
  const padT = 20
  const padB = 32
  const chartW = w - padL - padR
  const chartH = h - padT - padB
  const n = trend.length

  ctx.strokeStyle = 'rgba(255,255,255,0.06)'
  ctx.lineWidth = 1
  for (let i = 0; i <= 4; i++) {
    const y = padT + (chartH / 4) * i
    ctx.beginPath()
    ctx.moveTo(padL, y)
    ctx.lineTo(padL + chartW, y)
    ctx.stroke()
  }

  const points = trend.map((item, i) => ({
    x: padL + (n <= 1 ? chartW / 2 : (i / (n - 1)) * chartW),
    y: padT + chartH - (Math.max(0, Math.min(100, item.score)) / 100) * chartH,
    date: item.date,
  }))

  ctx.strokeStyle = '#ff4d4f'
  ctx.lineWidth = 2
  ctx.beginPath()
  points.forEach((p, i) => {
    if (i === 0) ctx.moveTo(p.x, p.y)
    else ctx.lineTo(p.x, p.y)
  })
  ctx.stroke()

  points.forEach((p, i) => {
    ctx.fillStyle = '#ff4d4f'
    ctx.beginPath()
    ctx.arc(p.x, p.y, 3, 0, Math.PI * 2)
    ctx.fill()
    if (i === 0 || i === Math.floor((n - 1) / 2) || i === n - 1) {
      ctx.fillStyle = '#6b7280'
      ctx.font = '10px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(String(p.date), p.x, padT + chartH + 14)
    }
  })
}

function applyData(data) {
  const displayScore = data.displayScore != null ? data.displayScore : data.score
  const level = getDisplayLevel(displayScore)
  const quote = dailyQuote(data.adviceDate || data.date)
  const quoteText = String(data.dailyQuote || quote.text)
  const formattedQuote = /[。！？；…]$/.test(quoteText) ? quoteText : `${quoteText}。`

  $('#headerDate').textContent = formatHeaderDate()
  $('#generatedAt').textContent = data.generatedAtLabel || data.generatedAt || '更新中'
  $('#quoteText').textContent = formattedQuote
  $('#levelLabel').textContent = data.levelLabel || data.displayLevel || level.label
  $('#levelLabel').className = `gauge-level ${data.levelClass || level.class}`
  $('#positionDesc').textContent = data.positionDesc || ''
  $('#displayScore').textContent = displayScore
  $('#displayScore').className = `gauge-score ${data.levelClass || level.class}`

  const foot = $('#baselineFoot')
  if (data.scoreMode === 'live' && data.baselineScore != null) {
    foot.hidden = false
    $('#baselineLine').textContent = `基准分 ${data.baselineScore}`
  } else {
    foot.hidden = true
  }

  const emptyTip = $('#emptyTip')
  if (data.emptyWarning) {
    emptyTip.hidden = false
    const reason = (data.emptyReasons && data.emptyReasons[0]) || '综合情绪偏弱'
    emptyTip.textContent = `龙空风险提示 · ${reason}（本人复盘，非投资建议）`
  } else {
    emptyTip.hidden = true
  }

  setupGaugeCanvas($('#gaugeCanvas'), displayScore)
  renderSections(normalizeSections(data.indicatorSections))
  drawTrend($('#trendCanvas'), data.trend || [])

  $('#statusBar').textContent = `参考日 ${data.refDate || data.adviceDate || '--'} · 数据已更新`
  $('#statusBar').className = 'status-bar ok'
}

function showError(err) {
  const msg = err?.warming
    ? '服务端正在预热缓存，约 5 秒后自动重试…'
    : (err?.message || '加载失败')
  $('#statusBar').textContent = msg
  $('#statusBar').className = 'status-bar err'
}

function showLoading() {
  $('#statusBar').textContent = '正在加载市场数据…'
  $('#statusBar').className = 'status-bar'
  $('#loadingSkeleton').hidden = false
  $('#contentBlock').hidden = true
}

function hideLoading() {
  $('#loadingSkeleton').hidden = true
  $('#contentBlock').hidden = false
}

let retryTimer = null
let refreshTimer = null

export async function loadHome(options = {}) {
  const { silent = false } = options
  if (!silent) {
    showLoading()
  } else {
    const bar = $('#statusBar')
    if (bar && bar.className.includes('ok')) {
      bar.textContent = '后台更新中…'
      bar.className = 'status-bar'
    }
  }
  try {
    const data = await fetchToday()
    if (!silent) hideLoading()
    applyData(data)
    if (retryTimer) {
      clearTimeout(retryTimer)
      retryTimer = null
    }
  } catch (err) {
    if (!silent) hideLoading()
    if (silent) {
      const bar = $('#statusBar')
      if (bar) {
        bar.textContent = `自动刷新失败：${err?.message || '请稍后重试'}`
        bar.className = 'status-bar err'
      }
    } else {
      showError(err)
    }
    if (err?.warming || /timeout|abort/i.test(String(err.message || err))) {
      retryTimer = setTimeout(() => loadHome({ silent }), err?.warming ? 5000 : 8000)
    }
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer = setInterval(() => {
    if (document.hidden) return
    loadHome({ silent: true })
  }, AUTO_REFRESH_MS)
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

export function initHomePage() {
  $('#refreshBtn')?.addEventListener('click', () => loadHome())
  window.addEventListener('resize', () => {
    const score = Number($('#displayScore')?.textContent)
    if (!Number.isNaN(score)) setupGaugeCanvas($('#gaugeCanvas'), score)
    drawTrend($('#trendCanvas'), window.__lastTrend || [])
  })
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) loadHome({ silent: true })
  })
  loadHome()
  startAutoRefresh()
}
