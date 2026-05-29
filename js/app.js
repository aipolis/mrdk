import { AUTO_REFRESH_MS } from './config.js?v=20260529i'
import { getDisplayLevel, dailyQuote, formatHeaderDate } from './theme.js?v=20260529i'
import { normalizeSections } from './indicators.js?v=20260529i'
import {
  buildLongkongHeroText,
  resolveLongkongState,
  resolveLongkongTone,
  renderLongkongLightsHtml,
  setGaugeLevelClass,
} from './longkongState.js?v=20260529k'
import { fetchToday, fetchHistory, fetchDay } from './api.js?v=20260529i'
import { createTrendController } from './trendDraw.js?v=20260529i'
import { createGaugeController, IDLE_MIN_MS, SKIP_ANIM_MS } from './gaugeAnim.js?v=20260529m'
import { getHomeCache, saveHomeCache, isSameHomeSnapshot } from './homeCache.js?v=20260529m'

export { fetchToday, fetchHistory }

const LOADING_DESC = '正在汇总昨日收盘数据…'
const HOME_QUOTE = '不怕错过，就怕做错。不出门的时候，就在家修炼。'

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

function normalizeRiskReason(reason) {
  const raw = String(reason || '').trim()
  if (!raw) return '接力环境偏谨慎'

  const promote = raw.match(/晋级率(?:仅|只有)?\s*(\d+(?:\.\d+)?)%/)
  if (promote) return `昨日涨停股今日晋级率仅 ${promote[1]}%，也就是昨日涨停股中今天继续涨停的比例偏低`

  const breakRate = raw.match(/炸板率(?:高达|达到|为)?\s*(\d+(?:\.\d+)?)%/)
  if (breakRate) return `炸板率 ${breakRate[1]}%，封板稳定性不足`

  return raw
}

function buildRiskCopy(data) {
  if (!data?.emptyWarning) return null
  const reason = normalizeRiskReason((data.emptyReasons && data.emptyReasons[0]) || '')
  return {
    desc: '分数中性，但接力晋级偏弱',
    tip: `复盘提示：${reason}。打板少做、精选，等更强确认。`,
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
      const showPrev = section.id === 'yesterday' || section.id === 'auction' || section.id === 'intraday' || section.id === 'longkongRisk'
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
  if (lightsEl) lightsEl.innerHTML = renderLongkongLightsHtml(lk.state, tone.class)
}

function applyData(data, options = {}) {
  const { silent = false, skipAnim = false, fastReveal = false } = options
  const displayScore = data.displayScore != null ? data.displayScore : data.score
  const level = getDisplayLevel(displayScore)
  const quoteText = HOME_QUOTE
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
    emptyTip.textContent = buildRiskCopy(data)?.tip || '复盘提示：综合情绪偏弱，打板少做、精选，等更强确认。'
  } else {
    emptyTip.hidden = true
  }

  renderSections(normalizeSections(data.indicatorSections, data))

  if (data.archiveFallback) {
    $('#statusBar').textContent = `首页缓存更新中，暂显示 ${data.refDate || data.adviceDate || '--'} 归档数据`
    $('#statusBar').className = 'status-bar err'
  } else {
    $('#statusBar').textContent = `参考日 ${data.refDate || data.adviceDate || '--'} · 数据已更新`
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
      id: 'peripheral',
      title: '今天外围情绪及指数',
      meta: '归档数据',
      layout: 'row3',
      cols: 3,
      items: detail?.peripheral || [],
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
    peripheral: detail?.peripheral || [],
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
  renderSections(normalizeSections(enriched.indicatorSections, enriched))
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
    hydrateHomeExtras(data).catch(() => {})
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
