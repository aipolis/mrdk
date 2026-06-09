import { resolveAutoRefreshMs } from './config.js?v=20260531a'
import { getDisplayLevel, dailyQuote, formatHeaderDate, HOME_QUOTE } from './theme.js?v=20260531a'
import { normalizeSections } from './indicators.js?v=20260609b'
import {
  buildLongkongHeroText,
  resolveLongkongState,
  resolveLongkongTone,
  renderLongkongLightsHtml,
  setGaugeLevelClass,
  normalizeRiskReason,
  buildRiskCopy,
} from './longkongState.js?v=20260604c'
import { fetchToday, fetchHistory, fetchDay, fetchIntradaySeries } from './api.js?v=20260529i'
import { drawIntradayChart } from './intradayChart.js?v=20260604c'
import { createTrendController } from './trendDraw.js?v=20260529i'
import { createGaugeController, IDLE_MIN_MS, SKIP_ANIM_MS } from './gaugeAnim.js?v=20260529m'
import { getHomeCache, saveHomeCache, isSameHomeSnapshot } from './homeCache.js?v=20260529m'

export { fetchToday, fetchHistory }

const LOADING_DESC = '正在汇总昨日收盘数据…'


const $ = (sel) => document.querySelector(sel)

/**
 * 根据 ref_d / advice_d / scoreMode 组合出有意义的状态栏文字。
 *
 * 盘中 (live)       → "今日实时情绪 · HH:MM 更新"
 * ref != advice     → "昨日收盘情绪 · 今日参考" / "周五收盘情绪 · 下周一参考"
 * ref == advice today → "今日收盘情绪 · 明日参考"
 */
function buildStatusText(data) {
  if (!data) return '数据加载中…'
  const scoreMode = data.scoreMode || 'baseline'
  const updTime   = data.generatedAtTime || ''

  // 盘中实时
  if (scoreMode === 'live') {
    return `今日实时情绪${updTime ? ' · ' + updTime + ' 更新' : ''}`
  }

  const refLabel = _dateMMDD(data.refDate)

  const refKey  = _dateKey(data.refDate)
  const advKey  = _dateKey(data.adviceDate || data.date)
  const todayKey = _dateKey(new Date())

  // ref 与 advice 是同一天 & 是今天（今日收盘 → 明日参考）
  if (refKey && refKey === advKey && advKey === todayKey) {
    return `今日收盘情绪 · 明日参考`
  }

  // advice 是今天
  if (advKey === todayKey) {
    return `${refLabel}收盘情绪 · 今日参考`
  }

  // advice 是未来（周末 / 节假日），统一显示「下一交易日」
  return `${refLabel}收盘情绪 · 下一交易日参考`
}

function _dateKey(raw) {
  if (!raw) return ''
  if (raw instanceof Date) {
    return raw.toISOString().slice(0, 10).replace(/-/g, '')
  }
  return String(raw).replace(/\D/g, '').slice(0, 8)
}

function _dateMMDD(raw) {
  const s = _dateKey(raw)
  if (s.length !== 8) return s || '--'
  return `${parseInt(s.slice(4, 6), 10)}月${parseInt(s.slice(6, 8), 10)}日`
}

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
  const riskCopy = buildRiskCopy(data)
  const levelLabel = data.levelLabel || data.displayLevel || meta.levelLabel || level.label
  const levelClass = data.levelClass || meta.levelClass || level.class
  const positionDesc = riskCopy?.desc || data.positionDesc || meta.positionDesc || ''

  applyLongkongState({
    ...data,
    displayScore,
    levelLabel,
    levelClass,
    positionDesc,
  })
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
  applyLongkongState({
    displayScore: '--',
    positionDesc: LOADING_DESC,
    levelLabel: '计算中',
    levelClass: 'calculating',
  })
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
  const remain = options.fastReveal
    ? 120
    : Math.max(600, IDLE_MIN_MS - elapsed)

  gaugeIdleTimer = setTimeout(() => {
    gaugeIdleTimer = null
    ctrl.settleTo(displayScore, done)
  }, remain)
}

const SECTOR_BAR_MAX = 30

function renderSectorBars(items) {
  if (!items?.length) return '<p class="grid-empty">暂无概念数据</p>'
  const bars = items.map(s => {
    const count = Number(s.count ?? 0)
    const pct = Math.min(100, Math.round(count / SECTOR_BAR_MAX * 100))
    const label = count > 0 ? `${count}家` : '--'
    return `
    <div class="sector-bar-row">
      <div class="sector-bar-head">
        <span class="sector-bar-name" title="${esc(s.name)}">${esc(s.name)}</span>
        <span class="sector-bar-count">${label}</span>
      </div>
      <div class="sector-bar-track">
        <div class="sector-bar-fill" style="width:${pct}%"></div>
      </div>
    </div>`
  }).join('')
  return `<div class="sector-bars">${bars}</div>`
}

function renderTimeseries(section) {
  const id = `intraday-chart-${Math.random().toString(36).slice(2, 7)}`
  // canvas is populated after render via initIntradayChart
  return `<canvas class="intraday-chart-canvas" id="${id}" data-series="${esc(JSON.stringify(section.series || []))}"></canvas>`
}

function renderGridSection(section) {
  if (section.layout === 'timeseries') {
    return renderTimeseries(section)
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
      const showPrev = section.id === 'yesterday' || section.id === 'auction' || section.id === 'intraday' || section.id === 'longkongRisk'
      const prev = showPrev
        ? `<span class="grid9-sub"><span class="grid9-sub-prefix">${prefix}</span><span class="grid9-sub-val">${esc(prevText)}</span></span>`
        : '<span class="grid9-sub grid9-sub--empty"></span>'
      const suffix = cell.displaySuffix ? `<span class="grid9-suffix">${esc(cell.displaySuffix)}</span>` : ''
      html += `
        <article class="grid9-cell" data-key="${esc(cell.key || '')}">
          <span class="grid9-value-row">
            <span class="grid9-value ${esc(cell.valueClass || '')}">${esc(cell.displayValue || cell.value || '--')}</span>
            ${arrow ? `<span class="trend-arrow ${good ? 'trend-good' : 'trend-bad'}">${arrow}</span>` : ''}
          </span>
          <span class="grid9-label">${esc(cell.label)}${suffix}</span>
          ${prev}
        </article>
      `
    }
    html += '</section>'
  }
  html += '</section>'
  return html
}

function renderSections(sections, homeData) {
  const box = $('#sections')
  if (!box) return
  if (!sections?.length) {
    box.innerHTML = '<p class="grid-empty">暂无指标数据</p>'
    return
  }
  box.innerHTML = sections.map((sec) => {
    const isIntraday = sec.id === 'intraday'
    const isAuction = sec.id === 'auction'
    const sectionClass = isAuction ? 'section section--drill' : 'section'
    const cardClass = isAuction ? 'card section-card section-card--drill' : (isIntraday ? 'card section-card section-card--intraday' : 'card section-card')
    const metaHtml = isAuction
      ? `<span class="section-meta-row"><span class="section-meta">${esc(sec.meta || '')}</span><span class="section-chevron" aria-hidden="true">›</span></span>`
      : `<span class="section-meta">${esc(sec.meta || '')}</span>`
    const cardContent = isIntraday
      ? `<canvas class="intraday-chart-canvas" aria-hidden="true"></canvas>${renderGridSection(sec)}`
      : renderGridSection(sec)
    return `
    <section class="${sectionClass}" data-drill-href="${isAuction ? '/auction.html' : ''}">
      <header class="section-head">
        <h2 class="section-title">${esc(sec.title)}</h2>
        ${metaHtml}
      </header>
      <article class="${cardClass}">${cardContent}</article>
    </section>`
  }).join('')
  // post-render: expand sector bar cells and paint intraday canvases
  _postRenderSections(box, sections, homeData)
}

// homeData: the raw API data object (may have top-level sectorConcentration)
function _postRenderSections(box, sections, homeData) {
  // ── 概念集中度柱状图 ────────────────────────────────────────
  // 优先从 homeData 顶层字段取（不依赖 grid 单元格是否存在）
  const sc = homeData?.sectorConcentration
  const topSectors = sc?.topSectors?.length ? sc.topSectors
    : (sections || []).flatMap(s => s.items || [])
        .find(it => it.key === 'sectorConcentration')?.topSectors
  if (topSectors?.length) {
    // 注入到"情绪概览"或"yesterday"section 下方
    const yesterdaySec = [...box.querySelectorAll('.section')]
      .find(el => {
        const title = el.querySelector('.section-title')?.textContent || ''
        return title.includes('情绪概览')
      })
    if (yesterdaySec && !yesterdaySec.querySelector('.sector-bars-card')) {
      const barsEl = document.createElement('article')
      barsEl.className = 'card sector-bars-card'
      barsEl.innerHTML = renderSectorBars(topSectors)
      yesterdaySec.appendChild(barsEl)
    }
  }
  // ── 盘中分时图 ──────────────────────────────────────────────
  box.querySelectorAll('.section--drill .section-card--drill').forEach((card) => {
    const section = card.closest('.section--drill')
    const href = section?.dataset?.drillHref
    if (!href || card.dataset.drillBound) return
    card.dataset.drillBound = '1'
    card.setAttribute('role', 'link')
    card.setAttribute('tabindex', '0')
    card.setAttribute('aria-label', '查看竞价明细')
    const go = () => { window.location.href = href }
    card.addEventListener('click', go)
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        go()
      }
    })
  })
  // ── 盘中分时图（canvas） ────────────────────────────────────
  box.querySelectorAll('.intraday-chart-canvas').forEach(canvas => {
    try {
      const series = JSON.parse(canvas.dataset.series || '[]')
      drawIntradayChart(canvas, series)
    } catch (_) {}
  })
}

let _intradaySeriesCache = null
async function loadAndRenderIntradayChart(sections) {
  const intradaySec = sections?.find(s => s.id === 'intraday')
  if (!intradaySec) return
  try {
    const data = _intradaySeriesCache || await fetchIntradaySeries()
    _intradaySeriesCache = data
    const series = data?.series || []
    document.querySelectorAll('.intraday-chart-canvas').forEach(canvas => {
      drawIntradayChart(canvas, series)
    })
  } catch (_) {}
}

function applyLongkongState(data) {
  const lk = resolveLongkongState(data)
  const tone = resolveLongkongTone(data)
  const hero = buildLongkongHeroText(data, lk)
  const root = $('#longkongState')
  if (!root) return
  root.hidden = false
  root.dataset.state = lk.state
  setGaugeLevelClass(root, tone.class)
  const heroEl = $('#longkongStateHero')
  const labelEl = $('#longkongStateLabel')
  const levelEl = $('#longkongStateLevel')
  const lightsEl = $('#longkongLights')
  const descEl = $('#longkongStateDesc')
  setGaugeLevelClass(heroEl, tone.class)
  if (labelEl) {
    labelEl.textContent = lk.label
    labelEl.className = `longkong-state-active ${tone.class}`
  }
  if (levelEl) {
    const levelClass = data?.levelClass === 'calculating' ? 'calculating' : tone.class
    if (hero.levelLabel) {
      levelEl.hidden = false
      levelEl.textContent = hero.levelLabel
      levelEl.className = `longkong-state-level ${levelClass}`
    } else {
      levelEl.hidden = true
      levelEl.textContent = ''
    }
  }
  if (descEl) {
    descEl.textContent = hero.desc || lk.desc || ''
    descEl.className = `longkong-state-desc ${tone.class}`
    descEl.hidden = !descEl.textContent
  }
  if (lightsEl) lightsEl.innerHTML = renderLongkongLightsHtml(lk.state, tone.class, data?.riskLevel || 'none')
}

function applyData(data, options = {}) {
  const { silent = false, skipAnim = false, fastReveal = false } = options
  const displayScore = data.displayScore != null ? data.displayScore : data.score
  const level = getDisplayLevel(displayScore)
  const quoteText = HOME_QUOTE
  const formattedQuote = /[。！？；…]$/.test(quoteText) ? quoteText : `${quoteText}。`

  $('#headerDate').textContent = formatHeaderDate()
  const _isLive = data.scoreMode === 'live'
  const _hm = data.generatedAtTime || '15:00'
  const _dateLabel = _isLive ? '今日' : _dateMMDD(data.refDate)
  $('#generatedAt').textContent = `${_dateLabel} ${_hm} 更新`
  $('#quoteText').textContent = formattedQuote

  gaugePendingMeta = {
    levelLabel: data.levelLabel || data.displayLevel || level.label,
    levelClass: data.levelClass || level.class,
    positionDesc: data.positionDesc || '',
  }

  if (!silent) {
    applyLongkongState({
      ...data,
      displayScore,
      positionDesc: LOADING_DESC,
      levelLabel: '计算中',
      levelClass: 'calculating',
    })
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
    emptyTip.textContent = buildRiskCopy(data)?.tip || '复盘｜重点：接力结构偏弱；应对：控制节奏，等待确认。'
  } else {
    emptyTip.hidden = true
  }

  renderSections(normalizeSections(data.indicatorSections, data), data)

  if (data.archiveFallback) {
    $('#statusBar').textContent = `缓存更新中，暂显示 ${buildStatusText(data)}`
    $('#statusBar').className = 'status-bar err'
  } else {
    $('#statusBar').textContent = buildStatusText(data)
    $('#statusBar').className = 'status-bar ok'
  }

  if (silent || skipAnim) {
    stopGaugeAnimation()
    ensureGaugeCtrl().drawFinal(displayScore)
    applyGaugeMeta(data, displayScore, level)
  } else {
    finishGaugeAnimation(displayScore, data, level, { fastReveal })
  }
}

function showError(err) {
  const msg = err?.warming
    ? `缓存更新中，约 ${err.retryAfterSec || 5} 秒后自动重试…`
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

function formatTradeDate(raw) {
  const d = tradeDateKey(raw)
  if (d.length !== 8) return raw || '--'
  return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`
}

function latestHistoryDate(histList) {
  const rows = Array.isArray(histList) ? histList : []
  for (const row of rows) {
    const d = tradeDateKey(row?.date || row?.tradeDate)
    if (d) return d
  }
  return ''
}

function buildArchiveSections(detail) {
  if (Array.isArray(detail?.indicatorSections) && detail.indicatorSections.length) {
    return detail.indicatorSections
  }
  return [
    {
      id: 'yesterday',
      title: '今天情绪概览',
      meta: detail?.tradeDate ? `归档 ${formatTradeDate(detail.tradeDate)}` : '归档数据',
      layout: 'grid3',
      cols: 3,
      items: detail?.grid9 || [],
    },
    {
      id: 'auction',
      title: '今天竞价情绪',
      meta: '归档数据',
      layout: 'grid3',
      cols: 3,
      items: detail?.auction || [],
    },
  ]
}

function archiveHomeData(detail, histList, err) {
  const sentiment = detail?.sentiment || {}
  const metrics = detail?.metrics || {}
  const hist = (Array.isArray(histList) ? histList : []).find((i) => (
    tradeDateKey(i?.date || i?.tradeDate) === tradeDateKey(detail?.tradeDate || metrics?.date || detail?.date)
  )) || {}
  const refDate = formatTradeDate(detail?.tradeDate || metrics?.date || detail?.date || hist?.date)
  const score = Number(sentiment.displayScore ?? sentiment.score ?? hist.score ?? 0)
  const level = getDisplayLevel(score)

  return {
    ...detail,
    adviceDate: refDate,
    refDate,
    date: refDate,
    generatedAt: `归档 ${refDate}`,
    generatedAtLabel: `归档 ${refDate}`,
    score,
    displayScore: score,
    baselineScore: score,
    scoreMode: sentiment.scoreMode || 'archive',
    levelLabel: hist.level || sentiment.level || level.label,
    displayLevel: hist.level || sentiment.level || level.label,
    levelClass: hist.levelClass || sentiment.levelClass || level.class,
    levelColor: sentiment.levelColor || level.color,
    positionDesc: '首页缓存更新中，暂显示最近归档数据',
    emptyWarning: Boolean(sentiment.emptyWarning),
    emptyReasons: sentiment.emptyReasons || [],
    baselineEmptyWarning: Boolean(sentiment.emptyWarning),
    baselineEmptyReasons: sentiment.emptyReasons || [],
    grid9: detail?.grid9 || [],
    auction: detail?.auction || [],
    intraday: [],
    metrics,
    prevMetrics: {},
    indicatorSections: buildArchiveSections(detail),
    archiveFallback: true,
    archiveFallbackReason: err?.message || '缓存更新中',
    staleContext: err?.staleContext || null,
  }
}

async function loadArchiveFallback(err, histData) {
  const histList = histData?.list || histData || []
  const cachedDate = tradeDateKey(err?.staleContext?.cached?.ref_d)
  const latestDate = cachedDate || latestHistoryDate(histList)
  if (!latestDate) throw err
  const detail = await fetchDay(latestDate)
  return {
    data: archiveHomeData(detail, histList, err),
    histList,
  }
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

async function hydrateHomeExtras(data) {
  const histData = await fetchHistory(20).catch(() => null)
  const histList = histData?.list || histData || []
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

  const enriched = await attachAuctionArchives({ ...data }, histList)
  const normalizedSections = normalizeSections(enriched.indicatorSections, enriched)
  renderSections(normalizedSections, enriched)
  loadAndRenderIntradayChart(normalizedSections).catch(() => {})
  if (!isSameHomeSnapshot(data, enriched)) {
    saveHomeCache(enriched)
  }
  return enriched
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
    const data = await fetchToday()
    const elapsed = Date.now() - (gaugeFetchStartAt || Date.now())
    const fastReveal = elapsed > 2000 || elapsed < SKIP_ANIM_MS
    if (!silent) {
      hideLoading()
      beginGaugeLoading()
    }
    applyData(data, { silent, skipAnim: silent, fastReveal: !silent && fastReveal })
    saveHomeCache(data)
    hydrateHomeExtras(data).catch((e) => console.warn('[hydrateHomeExtras]', e))
    if (retryTimer) {
      clearTimeout(retryTimer)
      retryTimer = null
    }
  } catch (err) {
    const contentHidden = $('#contentBlock')?.hidden !== false
    let showedFallback = false
    if (err?.warming) {
      try {
        const histData = await fetchHistory(20).catch(() => null)
        const fallback = await loadArchiveFallback(err, histData)
        if (!silent) {
          hideLoading()
          beginGaugeLoading()
        }
        await attachAuctionArchives(fallback.data, fallback.histList)
        applyData(fallback.data, { silent })
        if (Array.isArray(fallback.histList) && fallback.histList.length) {
          initTrendController().setHistoryList(fallback.histList)
        }
        showedFallback = true
      } catch (fallbackErr) {
        if (!silent) hideLoading()
        showError(fallbackErr)
      }
    } else if (silent) {
      const bar = $('#statusBar')
      if (bar) {
        bar.textContent = `自动刷新失败：${err?.message || '请稍后重试'}`
        bar.className = 'status-bar err'
      }
    } else {
      hideLoading()
      showError(err)
    }
    if (err?.warming || /timeout|abort/i.test(String(err.message || err))) {
      const delay = err?.warming ? Math.max(2000, Number(err.retryAfterSec || 5) * 1000) : 8000
      retryTimer = setTimeout(() => loadHome({ silent: showedFallback || (silent && !contentHidden) }), delay)
    }
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  const tick = () => {
    if (document.hidden) {
      refreshTimer = setTimeout(tick, resolveAutoRefreshMs())
      return
    }
    loadHome({ silent: true }).finally(() => {
      refreshTimer = setTimeout(tick, resolveAutoRefreshMs())
    })
  }
  refreshTimer = setTimeout(tick, resolveAutoRefreshMs())
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearTimeout(refreshTimer)
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

  const cached = getHomeCache()
  if (cached) {
    gaugeFetchStartAt = Date.now()
    hideLoading()
    applyData(cached, { silent: true })
    if (Array.isArray(cached.trend) && cached.trend.length) {
      initTrendController().setHistoryList(
        cached.trend.slice().reverse().map((item) => ({
          date: item.date,
          score: item.score,
        }))
      )
    }
    loadHome({ silent: true })
  } else {
    loadHome()
  }
  startAutoRefresh()
}
