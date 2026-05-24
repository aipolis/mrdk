/** 情绪分趋势柱状图 + 周期切换 */

export const TREND_PERIODS = [5, 10, 20]

export function formatChartDate(raw) {
  const s = String(raw ?? '')
  const full = s.match(/(\d{4})-(\d{2})-(\d{2})/)
  if (full) return `${full[2]}-${full[3]}`
  const short = s.match(/(\d{2})-(\d{2})/)
  if (short) return `${short[1]}-${short[2]}`
  return s.length >= 5 ? s.slice(-5) : s || '--'
}

/** 历史列表（新→旧）→ 图表序列（旧→新） */
export function historyToTrend(list, days) {
  const n = Math.max(1, Math.min(days, TREND_PERIODS[TREND_PERIODS.length - 1]))
  return (list || [])
    .slice(0, n)
    .slice()
    .reverse()
    .map((item) => ({
      date: formatChartDate(item.date),
      score: Math.max(0, Math.min(100, Number(item.score) || 0)),
    }))
}

function barColor(score) {
  if (score >= 80) return '#cf1322'
  if (score >= 60) return '#ff4d4f'
  if (score >= 40) return '#faad14'
  if (score >= 20) return '#52c41a'
  return '#1890ff'
}

function shouldShowDateLabel(i, n) {
  if (n <= 8) return true
  if (i === 0 || i === n - 1) return true
  const step = Math.max(1, Math.ceil(n / 6))
  return i % step === 0
}

export function drawTrendChart(canvas, trend) {
  if (!canvas) return
  const data = trend || []
  if (!data.length) {
    const ctx = canvas.getContext('2d')
    ctx?.clearRect(0, 0, canvas.width, canvas.height)
    return
  }

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
  const padR = 8
  const padT = 22
  const padB = 28
  const chartW = w - padL - padR
  const chartH = h - padT - padB
  const n = data.length

  ctx.strokeStyle = 'rgba(255,255,255,0.06)'
  ctx.lineWidth = 1
  for (let i = 0; i <= 4; i++) {
    const y = padT + (chartH / 4) * i
    ctx.beginPath()
    ctx.moveTo(padL, y)
    ctx.lineTo(padL + chartW, y)
    ctx.stroke()
  }

  ctx.fillStyle = '#6b7280'
  ctx.font = '9px sans-serif'
  ctx.textAlign = 'right'
  for (let i = 0; i <= 4; i++) {
    const y = padT + (chartH / 4) * i
    ctx.fillText(String(100 - i * 25), padL - 4, y + 3)
  }

  const gap = n > 12 ? 3 : 5
  const barW = Math.max(6, (chartW - gap * (n - 1)) / n)

  data.forEach((item, i) => {
    const score = item.score
    const barH = (score / 100) * chartH
    const x = padL + i * (barW + gap)
    const y = padT + chartH - barH

    ctx.fillStyle = barColor(score)
    if (ctx.roundRect) {
      ctx.beginPath()
      ctx.roundRect(x, y, barW, barH, [3, 3, 0, 0])
      ctx.fill()
    } else {
      ctx.fillRect(x, y, barW, barH)
    }

    if (barH >= 14) {
      ctx.fillStyle = 'rgba(255,255,255,0.92)'
      ctx.font = '9px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(String(score), x + barW / 2, y + 11)
    } else if (score > 0) {
      ctx.fillStyle = '#e5e7eb'
      ctx.font = '9px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(String(score), x + barW / 2, y - 4)
    }

    if (shouldShowDateLabel(i, n)) {
      ctx.fillStyle = '#6b7280'
      ctx.font = '9px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(String(item.date), x + barW / 2, padT + chartH + 14)
    }
  })
}

export function createTrendController(options) {
  const {
    canvas,
    titleEl,
    periodRoot,
    defaultDays = 10,
  } = options

  let days = defaultDays
  let historyList = []
  let trend = []

  function updateTitle() {
    if (titleEl) titleEl.textContent = `近 ${days} 日情绪趋势`
  }

  function syncPeriodButtons() {
    periodRoot?.querySelectorAll('[data-days]').forEach((btn) => {
      btn.classList.toggle('active', Number(btn.dataset.days) === days)
    })
  }

  function render() {
    trend = historyToTrend(historyList, days)
    drawTrendChart(canvas, trend)
  }

  function setHistoryList(list) {
    historyList = Array.isArray(list) ? list : []
    render()
  }

  function setDays(n) {
    if (!TREND_PERIODS.includes(n)) return
    days = n
    updateTitle()
    syncPeriodButtons()
    render()
  }

  periodRoot?.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-days]')
    if (!btn) return
    setDays(Number(btn.dataset.days))
  })

  setDays(defaultDays)
  return {
    setHistoryList,
    setDays,
    render,
    getTrend: () => trend,
  }
}

export function trendPeriodButtonsHtml(activeDays = 10) {
  return TREND_PERIODS.map((d) =>
    `<button type="button" class="trend-period${d === activeDays ? ' active' : ''}" data-days="${d}">${d}天</button>`
  ).join('')
}
