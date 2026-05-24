import { AUTO_REFRESH_MS } from './config.js'
import { drawSteeringGauge } from './gaugeDraw.js'
import { getDisplayLevel, dailyQuote, formatHeaderDate } from './theme.js'
import { normalizeSections } from './indicators.js'
import { fetchToday, fetchHistory, fetchDay } from './api.js'
import { createTrendController } from './trendDraw.js'

export { fetchToday, fetchHistory }

const $ = (sel) => document.querySelector(sel)

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
      const prevText = cell.prev && cell.prev !== '--' ? cell.prev : '--'
      const showPrev = section.id === 'auction' || (cell.prev && cell.prev !== '--')
      const prev = showPrev
        ? `<span class="grid9-sub"><span class="grid9-sub-prefix">${prefix}</span><span class="grid9-sub-val">${esc(prevText)}</span></span>`
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
  renderSections(normalizeSections(data.indicatorSections, data))

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

function tradeDateKey(raw) {
  return String(raw || '').replace(/-/g, '').slice(0, 8)
}

async function attachAuctionArchives(data, histList) {
  const refD = tradeDateKey(data.refDate)
  if (!refD) return data

  const rows = Array.isArray(histList) ? histList : []
  const refIdx = rows.findIndex((i) => tradeDateKey(i.date) === refD)
  const prevD = refIdx >= 0 ? tradeDateKey(rows[refIdx + 1]?.date) : ''

  const fetches = [fetchDay(refD).catch(() => null)]
  if (prevD && prevD !== refD) fetches.push(fetchDay(prevD).catch(() => null))
  const [refDetail, prevDetail] = await Promise.all(fetches)

  data.refAuctionArchive = refDetail?.auction || []
  data.prevAuctionArchive = prevDetail?.auction || []
  return data
}

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
    const [data, histData] = await Promise.all([
      fetchToday(),
      fetchHistory(20).catch(() => null),
    ])
    if (!silent) hideLoading()
    const histList = histData?.list || histData || []
    await attachAuctionArchives(data, histList)
    applyData(data)
    if (Array.isArray(histList) && histList.length) {
      initTrendController().setHistoryList(histList)
    } else if (Array.isArray(data.trend) && data.trend.length) {
      initTrendController().setHistoryList(
        data.trend.slice().reverse().map((item) => ({
          date: item.date,
          score: item.score,
        }))
      )
    }
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
  initTrendController()
  $('#refreshBtn')?.addEventListener('click', () => loadHome())
  window.addEventListener('resize', () => {
    const score = Number($('#displayScore')?.textContent)
    if (!Number.isNaN(score)) setupGaugeCanvas($('#gaugeCanvas'), score)
    trendCtrl?.render()
  })
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) loadHome({ silent: true })
  })
  loadHome()
  startAutoRefresh()
}
