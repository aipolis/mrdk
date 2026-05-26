import { AUTO_REFRESH_MS } from './config.js'
import { getDisplayLevel, dailyQuote, formatHeaderDate } from './theme.js'
import { normalizeSections } from './indicators.js'
import { fetchToday, fetchHistory, fetchDay } from './api.js'
import { createTrendController } from './trendDraw.js'
import { createGaugeController, IDLE_MIN_MS } from './gaugeAnim.js'

export { fetchToday, fetchHistory }

const LOADING_DESC = '正在汇总昨日收盘数据…'

const $ = (sel) => document.querySelector(sel)

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

let gaugeCtrl = null
let gaugeIdleTimer = null
let gaugePendingMeta = null
let gaugeFetchStartAt = 0

function ensureGaugeCtrl() {
  if (gaugeCtrl) return gaugeCtrl
  gaugeCtrl = createGaugeController({
    getTheme: () => 'dark',
    onScoreReveal: (score) => {
      setGaugeCalculating(false)
      const el = $('#displayScore')
      if (el) el.textContent = String(score)
    },
  })
  return gaugeCtrl
}

function bindGaugeCanvas() {
  return ensureGaugeCtrl().bindCanvas($('#gaugeCanvas'))
}

function setGaugeCalculating(on) {
  const dots = $('#gaugeDots')
  const score = $('#displayScore')
  const level = $('#levelLabel')
  if (dots) {
    dots.hidden = !on
    dots.setAttribute('aria-hidden', on ? 'false' : 'true')
  }
  if (score) score.hidden = on
  if (level && on) {
    level.textContent = '计算中'
    level.className = 'gauge-level calculating'
  }
}

function applyGaugeMeta(data, displayScore, level) {
  const meta = gaugePendingMeta || {}
  const levelLabel = data.levelLabel || data.displayLevel || meta.levelLabel || level.label
  const levelClass = data.levelClass || meta.levelClass || level.class
  const positionDesc = data.positionDesc || meta.positionDesc || ''

  $('#levelLabel').textContent = levelLabel
  $('#levelLabel').className = `gauge-level ${levelClass}`
  $('#positionDesc').textContent = positionDesc
  $('#displayScore').textContent = displayScore
  $('#displayScore').className = `gauge-score ${levelClass}`
  setGaugeCalculating(false)
}

function stopGaugeAnimation() {
  if (gaugeIdleTimer) {
    clearTimeout(gaugeIdleTimer)
    gaugeIdleTimer = null
  }
  ensureGaugeCtrl().stop()
}

function beginGaugeLoading() {
  gaugeFetchStartAt = Date.now()
  bindGaugeCanvas()
  setGaugeCalculating(true)
  $('#positionDesc').textContent = LOADING_DESC
  ensureGaugeCtrl().startIdle(IDLE_MIN_MS)
}

function finishGaugeAnimation(displayScore, data, level, options = {}) {
  const { skipAnim = false } = options
  const ctrl = ensureGaugeCtrl()
  bindGaugeCanvas()

  const done = () => {
    applyGaugeMeta(data, displayScore, level)
    gaugePendingMeta = null
  }

  if (skipAnim) {
    stopGaugeAnimation()
    ctrl.drawFinal(displayScore)
    applyGaugeMeta(data, displayScore, level)
    gaugePendingMeta = null
    return
  }

  if (gaugeIdleTimer) {
    clearTimeout(gaugeIdleTimer)
    gaugeIdleTimer = null
  }

  if (!ctrl.isIdle()) {
    setGaugeCalculating(true)
    ctrl.startIdle(IDLE_MIN_MS)
    gaugeFetchStartAt = Date.now()
  }

  const elapsed = Date.now() - (gaugeFetchStartAt || Date.now())
  const remain = Math.max(600, IDLE_MIN_MS - elapsed)

  gaugeIdleTimer = setTimeout(() => {
    gaugeIdleTimer = null
    ctrl.settleTo(displayScore, done)
  }, remain)
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

  const prefix = '昨 '
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
            <span class="grid9-value ${esc(cell.valueClass || '')}">${esc(cell.displayValue || cell.value || '--')}</span>
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

function applyData(data, options = {}) {
  const { silent = false } = options
  const displayScore = data.displayScore != null ? data.displayScore : data.score
  const level = getDisplayLevel(displayScore)
  const quote = dailyQuote(data.adviceDate || data.date)
  const quoteText = String(data.dailyQuote || quote.text)
  const formattedQuote = /[。！？；…]$/.test(quoteText) ? quoteText : `${quoteText}。`

  $('#headerDate').textContent = formatHeaderDate()
  $('#generatedAt').textContent = data.generatedAtLabel || data.generatedAt || '更新中'
  $('#quoteText').textContent = formattedQuote

  gaugePendingMeta = {
    levelLabel: data.levelLabel || data.displayLevel || level.label,
    levelClass: data.levelClass || level.class,
    positionDesc: data.positionDesc || '',
  }

  if (!silent) {
    $('#positionDesc').textContent = LOADING_DESC
  }

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

  renderSections(normalizeSections(data.indicatorSections, data))

  $('#statusBar').textContent = `参考日 ${data.refDate || data.adviceDate || '--'} · 数据已更新`
  $('#statusBar').className = 'status-bar ok'

  if (silent) {
    stopGaugeAnimation()
    ensureGaugeCtrl().drawFinal(displayScore)
    applyGaugeMeta(data, displayScore, level)
  } else {
    finishGaugeAnimation(displayScore, data, level)
  }
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
    gaugeFetchStartAt = Date.now()
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
    if (!silent) beginGaugeLoading()
    await attachAuctionArchives(data, histList)
    applyData(data, { silent })
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
  bindGaugeCanvas()
  $('#refreshBtn')?.addEventListener('click', () => loadHome())
  window.addEventListener('resize', () => {
    const ctrl = ensureGaugeCtrl()
    ctrl.bindCanvas($('#gaugeCanvas'))
    const score = Number($('#displayScore')?.textContent)
    if (!Number.isNaN(score) && $('#displayScore')?.hidden === false) {
      ctrl.drawFinal(score)
    }
    trendCtrl?.render()
  })
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) loadHome({ silent: true })
  })
  loadHome()
  startAutoRefresh()
}
