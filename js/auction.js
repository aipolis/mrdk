import { fetchAuctionDetail } from './api.js'
const $ = (sel) => document.querySelector(sel)

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
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </article>
  `
}

function renderVolumeSurge(stocks, sectors) {
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
  if (tab === 'oneWord') return renderOneWord(data.oneWordStocks)
  if (tab === 'topSectors') return renderTopSectors(data.topSectors, data.sourceNote)
  return renderVolumeSurge(data.volumeSurgeStocks, data.volumeSurgeSectors)
}

let activeTab = 'oneWord'
let pageData = null

function showPanel() {
  const box = $('#auctionPanels')
  if (!box || !pageData) return
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
}

async function loadDetail(force = false) {
  const status = $('#auctionStatus')
  const meta = $('#auctionMeta')
  const tabs = $('#auctionTabs')
  const panels = $('#auctionPanels')
  if (status) status.textContent = force ? '刷新中…' : '正在加载…'
  if (panels) panels.hidden = true
  if (tabs) tabs.hidden = true

  try {
    const date = queryDate()
    pageData = await fetchAuctionDetail(date)
    const ready = !!pageData.ready
    if (meta) {
      meta.textContent = ready
        ? `${pageData.tradeDate || ''} · ${pageData.updatedAt || ''} 更新`
        : '竞价数据等待 9:25 后更新'
    }
    if (status) status.textContent = ready ? '' : '竞价数据等待 9:25 后更新'
    if (ready) {
      if (tabs) tabs.hidden = false
      if (panels) panels.hidden = false
      showPanel()
    } else if (panels) {      panels.hidden = false
      panels.innerHTML = '<article class="card section-card"><p class="grid-empty">竞价数据等待 9:25 后更新</p></article>'
    }
  } catch (err) {
    if (status) status.textContent = err.message || '加载失败'
    if (meta) meta.textContent = '加载失败'
    if (panels) {
      panels.hidden = false
      panels.innerHTML = `<article class="card section-card"><p class="grid-empty">${esc(err.message || '加载失败')}</p></article>`
    }
  }
}

export function initAuctionPage() {
  document.querySelectorAll('.auction-tab').forEach((btn) => {
    btn.addEventListener('click', () => setActiveTab(btn.dataset.tab || 'oneWord'))
  })
  $('#refreshBtn')?.addEventListener('click', () => loadDetail(true))
  loadDetail()
}
