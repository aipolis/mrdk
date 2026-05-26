const { homeData, getPositionAdvice } = require('./data')

const { normalizeGrid9 } = require('./grid9')

const { normalizeIndicatorSections } = require('./indicators')

const { pickLatestGeneratedAt } = require('./indicatorDisplay')

const { withPreviewScore } = require('./preview')

const { getDisplayLevel } = require('./theme')

const { PREFETCH_TIMEOUT_MS, HOME_FETCH_TIMEOUT_MS, HTTP_TIMEOUT_MS } = require('./config')

const api = require('./api')
const { isDevtoolsEnv } = require('./api')

const { getHomeCache, isSameHomeSnapshot, saveHomeCache, getHomeCacheMeta, FRESH_TTL_MS } = require('./homeCache')
const { getHistoryCache, saveHistoryCache } = require('./historyCache')

let homeFetchInflight = null

function homeFetchOptions(options = {}) {
  const force = options.force === true
  const prefetch = options.prefetch === true
  const devtools = isDevtoolsEnv()
  let timeout = HOME_FETCH_TIMEOUT_MS || 45000
  if (prefetch || (devtools && !force)) timeout = PREFETCH_TIMEOUT_MS
  else if (force) timeout = HTTP_TIMEOUT_MS
  let maxAttempts = options.maxAttempts || (force ? 3 : 2)
  if (devtools && !force) maxAttempts = 1
  return {
    timeout: options.timeout || timeout,
    httpOnly: options.httpOnly === true || devtools,
    skipFallback: options.skipFallback === true || devtools,
    force,
    prefetch,
    maxAttempts
  }
}

function hasFreshHomeCache() {
  const meta = getHomeCacheMeta()
  if (!meta || !meta.data) return false
  return Date.now() - meta.ts <= FRESH_TTL_MS
}

function shouldSkipHomeNetwork(options = {}) {
  if (options.force) return false
  if (!isDevtoolsEnv()) return false
  return hasFreshHomeCache()
}

function tradeDateKey(raw) {
  return String(raw || '').replace(/-/g, '').slice(0, 8)
}

function attachAuctionArchives(raw, histList) {
  const data = raw || {}
  const refD = tradeDateKey(data.refDate || data.adviceDate || data.date)
  if (!refD) return Promise.resolve(data)

  const rows = Array.isArray(histList) ? histList : []
  const refIdx = rows.findIndex(item => tradeDateKey(item.date) === refD)
  const prevD = refIdx >= 0 ? tradeDateKey(rows[refIdx + 1] && rows[refIdx + 1].date) : ''

  const tasks = [api.getDaySentiment(refD).catch(() => null)]
  if (prevD && prevD !== refD) tasks.push(api.getDaySentiment(prevD).catch(() => null))

  return Promise.all(tasks).then(([refDetail, prevDetail]) => ({
    ...data,
    refAuctionArchive: (refDetail && refDetail.auction) || [],
    prevAuctionArchive: (prevDetail && prevDetail.auction) || [],
  }))
}



function applyHomeData(data) {

  const displayScore = data.displayScore != null ? data.displayScore : data.score
  const level = getDisplayLevel(displayScore)
  const advice = getPositionAdvice(displayScore)

  const positionPercent = data.positionPercent != null ? data.positionPercent : advice.percent

  const positionLabel = data.positionLabel || advice.label

  const positionDesc = data.positionDesc || advice.desc

  const emptyReasons = data.emptyReasons || []

  const emptyWarning = data.emptyWarning != null

    ? data.emptyWarning

    : (positionPercent === 0 || emptyReasons.length >= 2)



  const indicatorSections = normalizeIndicatorSections(data)

  const generatedAt = pickLatestGeneratedAt(data, indicatorSections)



  const result = {

    adviceDate: data.adviceDate || data.date,

    refDate: data.refDate || data.date,

    generatedAt,

    generatedAtLabel: data.generatedAtLabel || generatedAt,

    isReportReady: data.isReportReady !== false,

    date: data.adviceDate || data.date,

    dailyQuote: data.dailyQuote,

    score: displayScore,
    baselineScore: data.baselineScore != null ? data.baselineScore : data.score,
    liveScore: data.liveScore,
    displayScore,
    scoreMode: data.scoreMode || 'baseline',

    levelLabel: data.displayLevel || data.levelLabel || level.label,

    displayLevel: data.displayLevel || data.levelLabel || level.label,

    levelClass: data.levelClass || level.class,

    levelColor: data.levelColor || level.color,

    longkongSignal: data.longkongSignal,

    positionPercent,

    positionLabel,

    positionDesc,

    emptyWarning,

    emptyReasons,

    grid9: normalizeGrid9(data),

    intraday: data.intraday || [],

    indicatorSections,

    peripheral: data.peripheral || data.overview || [],

    auction: data.auction || [],

    overview: data.overview || data.peripheral || [],

    foreignCards: data.foreignCards || [],

    indicators: data.indicators || [],

    trend: data.trend || [],

    historyList: data.historyList || [],

    metrics: data.metrics || {},

    refAuctionArchive: data.refAuctionArchive || [],

    prevAuctionArchive: data.prevAuctionArchive || [],

    subscribePreview: data.subscribePreview || null

  }

  return withPreviewScore(result)

}



function fetchHomeFromNetwork(options = {}) {
  const reqOptions = homeFetchOptions(options)
  if (shouldSkipHomeNetwork(reqOptions)) {
    const cached = getHomeCache()
    if (cached) return Promise.resolve(cached)
  }
  if (options.reuseInflight !== false && homeFetchInflight) {
    return homeFetchInflight
  }
  homeFetchInflight = Promise.all([
    api.getTodaySentimentWithRetry(reqOptions),
    api.getHistory(20, { timeout: reqOptions.timeout, httpOnly: true }).catch(() => ({ list: [] })),
  ])
    .then(([raw, histData]) => {
      const histList = (histData && histData.list) || []
      return attachAuctionArchives(raw, histList).then(enriched => {
        const data = applyHomeData(enriched)
        data.historyList = histList
        saveHomeCache(data)
        return data
      })
    })
    .catch(err => {
      homeFetchInflight = null
      throw err
    })
    .finally(() => {
      homeFetchInflight = null
    })
  return homeFetchInflight
}



function prefetchHome() {
  return fetchHomeFromNetwork({ reuseInflight: true, prefetch: true, maxAttempts: 1 }).catch(() => null)
}



function fetchHome(options = {}) {

  const cached = !options.force && getHomeCache()

  if (options.cacheOnly) {

    return Promise.resolve(cached || applyHomeData(homeData))

  }

  const fetchOpts = {
    reuseInflight: !options.force,
    force: !!options.force
  }
  return fetchHomeFromNetwork(fetchOpts).catch(() => cached || applyHomeData(homeData))

}



function fetchHistory(days = 30, options = {}) {
  const fallback = () => {
    const { historyData } = require('./data')
    return { list: historyData.slice().reverse(), fromFallback: true }
  }
  const cached = !options.force && getHistoryCache()
  const req = api.getHistory(days, { timeout: options.timeout, httpOnly: true })
    .then(data => {
      const list = (data && data.list) || []
      if (list.length) saveHistoryCache(list)
      return data
    })

  if (cached && cached.length) {
    return req
      .then(data => {
        if ((data.list || []).length) return data
        return { list: cached, fromCache: true }
      })
      .catch(() => ({ list: cached, fromCache: true }))
  }

  return req.catch(() => fallback())
}



module.exports = {

  applyHomeData,

  fetchHome,

  fetchHomeFromNetwork,

  prefetchHome,

  getHomeCache,

  isSameHomeSnapshot,

  fetchHistory,

  getHistoryCache,

  shouldSkipHomeNetwork,

  hasFreshHomeCache,

}

