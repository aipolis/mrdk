import { fetchAuctionDetail } from './api.js'
import { resolveAuctionDetailPollMs, resolveVolumeSurgePollMs } from './config.js?v=20260531a'
const $ = (sel) => document.querySelector(sel)
const FAST_SECTIONS = 'oneWord,topSectors'
const SLOW_SECTIONS = 'volumeSurge'

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function queryDate() {
  const q = new URLSearchParams(window.location.search)
  return String(q.get('date') || '').replace(/-/g, '').slice(0, 8)
}

function pctClass(v) {
  const n = Number(v)
  if (Number.isNaN(n)) return ''
  return n >= 0 ? 'value-hot' : 'value-cold'
}

function skeletonPanel(label = '加载中…') {
  return `
    <article class="card section-card auction-skeleton">
      <p class="auction-skeleton-text">${esc(label)}</p>
      <span class="auction-skeleton-bar"></span>
      <span class="auction-skeleton-bar short"></span>
    </article>
  `
}

function renderOneWord(stocks) {
  if (!stocks?.length) {
    return '<article class="card section-card"><p class="grid-empty">暂无竞价一字个股</p></article>'
  }
  const rows = stocks.map((s) => `
    <tr>
      <td class="auction-name">
        <span class="auction-stock-name">${esc(s.name)}</span>
        <span class="auction-stock-code">${esc(s.code)}</span>
      </td>
      <td class="auction-num ${pctClass(s.openPct)}">${esc(s.openPctText)}</td>
      <td class="auction-num">${esc(s.sealAmountText)}</td>
      <td class="auction-sector">${esc(s.sector)}</td>
    </tr>
  `).join('')
  return `
    <article class="card section-card auction-table-wrap">
      <table class="auction-table">
        <thead>
          <tr>
            <th>个股</th>
            <th>涨幅</th>
            <th>封单</th>
            <th>板块</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </article>
  `
}

function renderTopSectors(sectors, note) {
  if (!sectors?.length) {
    return '<article class="card section-card"><p class="grid-empty">暂无板块数据</p></article>'
  }
  const noteHtml = note ? `<p class="auction-note">${esc(note)}</p>` : ''
  const rows = sectors.map((s, i) => `
    <tr>
      <td class="auction-rank">${i + 1}</td>
      <td>${esc(s.name)}</td>
      <td class="auction-num ${pctClass(s.chg)}">${esc(s.chgText)}</td>
      <td class="auction-num auction-muted">${esc(s.upCount)}/${esc(s.downCount)}</td>
      <td class="auction-num auction-muted">${esc(s.auctionAmountText || '--')}</td>
    </tr>
  `).join('')
  return `
    ${noteHtml}
    <article class="card section-card auction-table-wrap">
      <table class="auction-table">
        <thead>
          <tr>
            <th>#</th>
            <th>板块</th>
            <th>涨幅</th>
            <th>涨/跌</th>
            <th>竞价额</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </article>
  `
}

function renderVolumeSurge(stocks, sectors, loading = false) {
  if (loading) {
    return skeletonPanel('量能异动计算中，首次加载较慢…')
  }
  let html = '<h3 class="auction-subtitle">个股 · 竞价量较昨日 +15% 以上</h3>'
  if (!stocks?.length) {
    html += '<article class="card section-card"><p class="grid-empty">暂无量能异动个股（需有昨日竞价量缓存）</p></article>'
  } else {
    const rows = stocks.map((s) => `
      <tr>
        <td class="auction-name">
          <span class="auction-stock-name">${esc(s.name)}</span>
          <span class="auction-stock-code">${esc(s.code)}</span>
        </td>
        <td class="auction-num value-hot">${esc(s.volRatioText)}</td>
        <td class="auction-num auction-muted">${esc(s.auctionAmountText || '--')}</td>
        <td class="auction-sector">${esc(s.sector)}</td>
      </tr>
    `).join('')
    html += `
      <article class="card section-card auction-table-wrap">
        <table class="auction-table">
          <thead>
            <tr>
              <th>个股</th>
              <th>增幅</th>
              <th>竞价额</th>
              <th>板块</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </article>
    `
  }

  html += '<h3 class="auction-subtitle">板块排序 · 按异动家数</h3>'
  if (!sectors?.length) {
    html += '<article class="card section-card"><p class="grid-empty">暂无板块汇总</p></article>'
  } else {
    const rows = sectors.map((s) => `
      <tr>
        <td>${esc(s.sector)}</td>
        <td class="auction-num">${esc(s.count)}</td>
        <td class="auction-num auction-muted">${esc(s.totalAmountText || '--')}</td>
        <td class="auction-num value-hot">${esc(s.avgRatioText)}</td>
        <td class="auction-num value-hot">${esc(s.maxRatioText)}</td>
      </tr>
    `).join('')
    html += `
      <article class="card section-card auction-table-wrap">
        <table class="auction-table">
          <thead>
            <tr>
              <th>板块</th>
              <th>家数</th>
              <th>竞价额</th>
              <th>均增幅</th>
              <th>最大</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </article>
    `
  }
  return html
}

function renderPanel(tab, data) {
  if (tab === 'oneWord') {
    if (data._loadingOneWord) return skeletonPanel('竞价一字加载中…')
    return renderOneWord(data.oneWordStocks)
  }
  if (tab === 'topSectors') {
    if (data._loadingTopSectors) return skeletonPanel('板块 Top10 加载中…')
    return renderTopSectors(data.topSectors, data.sourceNote)
  }
  return renderVolumeSurge(
    data.volumeSurgeStocks,
    data.volumeSurgeSectors,
    !!data._loadingVolumeSurge,
  )
}

let activeTab = 'oneWord'
let pageData = {
  ready: false,
  oneWordStocks: [],
  topSectors: [],
  volumeSurgeStocks: [],
  volumeSurgeSectors: [],
  _volumeLoaded: false,
}

function showPanel() {
  const box = $('#auctionPanels')
  if (!box) return
  box.hidden = false
  box.innerHTML = `<section class="auction-panel" data-tab="${activeTab}">${renderPanel(activeTab, pageData)}</section>`
}

function setActiveTab(tab) {
  activeTab = tab
  document.querySelectorAll('.auction-tab').forEach((btn) => {
    const on = btn.dataset.tab === tab
    btn.classList.toggle('active', on)
    btn.setAttribute('aria-pressed', on ? 'true' : 'false')
  })
  showPanel()
  if (tab === 'volumeSurge' && (!pageData._volumeLoaded || inVolumeSurgeLiveWindow())) {
    loadVolumeSurge()
  }
}

function mergePayload(data) {
  pageData = {
    ...pageData,
    ...data,
    oneWordStocks: data.oneWordStocks ?? pageData.oneWordStocks,
    topSectors: data.topSectors ?? pageData.topSectors,
    volumeSurgeStocks: data.volumeSurgeStocks ?? pageData.volumeSurgeStocks,
    volumeSurgeSectors: data.volumeSurgeSectors ?? pageData.volumeSurgeSectors,
    _loadingOneWord: false,
    _loadingTopSectors: false,
  }
}

function updateMeta() {
  const meta = $('#auctionMeta')
  if (!meta) return
  if (!pageData.ready) {
    meta.textContent = '竞价数据等待 9:15 后更新'
    return
  }
  const hm = new Date().getHours() * 60 + new Date().getMinutes()
  if (hm >= 9 * 60 + 15 && hm < 9 * 60 + 20) {
    meta.textContent = `${pageData.tradeDate || ''} · 量能异动 9:20 后更新`
    return
  }  meta.textContent = `${pageData.tradeDate || ''} · ${pageData.updatedAt || ''} 更新`
}

function inVolumeSurgeLiveWindow(now = new Date()) {
  const hm = now.getHours() * 60 + now.getMinutes()
  return hm >= 9 * 60 + 20 && hm < 9 * 60 + 26
}

async function loadVolumeSurge(force = false) {
  if (pageData._loadingVolumeSurge) return
  const live = inVolumeSurgeLiveWindow()
  if (!force && pageData._volumeLoaded && !live) return
  pageData._loadingVolumeSurge = true
  if (activeTab === 'volumeSurge') showPanel()
  try {
    const data = await fetchAuctionDetail(queryDate(), SLOW_SECTIONS)
    pageData.volumeSurgeStocks = data.volumeSurgeStocks || []
    pageData.volumeSurgeSectors = data.volumeSurgeSectors || []
    pageData._volumeLoaded = data.volumeSurgeReady || !inVolumeSurgeLiveWindow()
  } catch (err) {
    pageData._volumeError = err.message || '量能异动加载失败'
  } finally {
    pageData._loadingVolumeSurge = false
    if (activeTab === 'volumeSurge') showPanel()
  }
}

async function loadDetail(force = false) {
  const status = $('#auctionStatus')
  const tabs = $('#auctionTabs')
  const panels = $('#auctionPanels')

  pageData._loadingOneWord = true
  pageData._loadingTopSectors = true
  if (!force) {
    pageData._volumeLoaded = false
    pageData._volumeRequested = false
    pageData._loadingVolumeSurge = false
  }
  if (tabs) tabs.hidden = false
  if (panels) {
    panels.hidden = false
    showPanel()
  }
  if (status) status.textContent = force ? '刷新中…' : '加载竞价一字与板块…'

  try {
    const data = await fetchAuctionDetail(queryDate(), FAST_SECTIONS)
    mergePayload(data)
    pageData.topSectorsReady = !!data.topSectorsReady
    pageData.volumeSurgeReady = !!data.volumeSurgeReady
    updateMeta()
    if (status) status.textContent = data.ready ? '' : '竞价数据等待 9:15 后更新'
    showPanel()
    if (inVolumeSurgeLiveWindow() || pageData.volumeSurgeReady) {
      loadVolumeSurge(force)
    }  } catch (err) {
    pageData._loadingOneWord = false
    pageData._loadingTopSectors = false
    if (status) status.textContent = err.message || '加载失败'
    if ($('#auctionMeta')) $('#auctionMeta').textContent = '加载失败'
    if (panels) {
      panels.innerHTML = `<article class="card section-card"><p class="grid-empty">${esc(err.message || '加载失败')}</p></article>`
    }
  }
}

export function initAuctionPage() {
  document.querySelectorAll('.auction-tab').forEach((btn) => {
    btn.addEventListener('click', () => setActiveTab(btn.dataset.tab || 'oneWord'))
  })
  $('#refreshBtn')?.addEventListener('click', () => loadDetail(true))
  if ($('#auctionTabs')) $('#auctionTabs').hidden = false
  showPanel()
  loadDetail()
  let fastPollTimer = null
  let volumePollTimer = null
  const scheduleFastPoll = () => {
    if (fastPollTimer) clearTimeout(fastPollTimer)
    const ms = resolveAuctionDetailPollMs()
    if (!ms) return
    fastPollTimer = setTimeout(async () => {
      if (!document.hidden) await loadDetail(true).catch(() => {})
      scheduleFastPoll()
    }, ms)
  }
  const scheduleVolumePoll = () => {
    if (volumePollTimer) clearTimeout(volumePollTimer)
    const ms = resolveVolumeSurgePollMs()
    volumePollTimer = setTimeout(async () => {
      if (!document.hidden && resolveVolumeSurgePollMs() > 0) {
        await loadVolumeSurge(true).catch(() => {})
      }
      scheduleVolumePoll()
    }, ms || 60 * 1000)
  }
  scheduleFastPoll()
  scheduleVolumePoll()
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      loadDetail(true).catch(() => {})
      if (inVolumeSurgeLiveWindow()) loadVolumeSurge(true).catch(() => {})
    }
  })}
