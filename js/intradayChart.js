/** 盘中分时走势图：canvas 渲染（按交易时段连续，午休不占位） */

const SESSION_START = 9 * 60 + 30   // 570
const MORNING_END = 11 * 60 + 30    // 690
const AFTERNOON_START = 13 * 60     // 780
const SESSION_END = 15 * 60         // 900
const MORNING_MINS = MORNING_END - SESSION_START       // 120
const AFTERNOON_MINS = SESSION_END - AFTERNOON_START   // 120
const TRADING_MINS = MORNING_MINS + AFTERNOON_MINS     // 240

function timeToMin(t) {
  const s = String(t || '').replace(':', '')
  if (s.length < 4) return null
  return parseInt(s.slice(0, 2), 10) * 60 + parseInt(s.slice(2, 4), 10)
}

/** 将时钟分钟映射为交易轴偏移；11:30–13:00 午休段折叠为 0 宽度 */
function clockMinToTradingOffset(min) {
  if (min == null || min < SESSION_START || min > SESSION_END) return null
  if (min <= MORNING_END) return min - SESSION_START
  if (min < AFTERNOON_START) return null
  return MORNING_MINS + (min - AFTERNOON_START)
}

function scoreToColor(score) {
  if (score >= 60) return '#f87171'
  if (score >= 50) return '#fbbf24'
  if (score >= 30) return '#38bdf8'
  return '#6b7280'
}

function hexToRgba(hex, alpha) {
  const h = String(hex).replace('#', '')
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
}

export function drawIntradayChart(canvas, series) {
  if (!canvas) return
  const dpr = window.devicePixelRatio || 1
  const W = canvas.offsetWidth || 320
  const H = canvas.offsetHeight || 90
  canvas.width = W * dpr
  canvas.height = H * dpr
  const ctx = canvas.getContext('2d')
  ctx.scale(dpr, dpr)

  const PAD = { top: 8, right: 12, bottom: 20, left: 28 }
  const cW = W - PAD.left - PAD.right
  const cH = H - PAD.top - PAD.bottom

  ctx.clearRect(0, 0, W, H)

  const toX = (offset) => PAD.left + (offset / TRADING_MINS) * cW
  const toY = (s) => PAD.top + cH * (1 - Math.max(0, Math.min(100, s)) / 100)

  const bands = [
    { lo: 60, hi: 100, color: 'rgba(248,113,113,0.06)' },
    { lo: 50, hi: 60, color: 'rgba(251,191,36,0.06)' },
    { lo: 30, hi: 50, color: 'rgba(56,189,248,0.06)' },
    { lo: 0, hi: 30, color: 'rgba(107,114,128,0.06)' },
  ]
  for (const b of bands) {
    const y1 = PAD.top + cH * (1 - b.hi / 100)
    const y2 = PAD.top + cH * (1 - b.lo / 100)
    ctx.fillStyle = b.color
    ctx.fillRect(PAD.left, y1, cW, y2 - y1)
  }

  ctx.strokeStyle = 'rgba(255,255,255,0.06)'
  ctx.lineWidth = 1
  for (const score of [30, 50, 60]) {
    const y = toY(score)
    ctx.beginPath()
    ctx.moveTo(PAD.left, y)
    ctx.lineTo(PAD.left + cW, y)
    ctx.stroke()
  }

  ctx.fillStyle = 'rgba(255,255,255,0.3)'
  ctx.font = `${9 * (dpr < 2 ? 1 : 0.8)}px system-ui,sans-serif`
  ctx.textAlign = 'right'
  for (const score of [30, 50, 60]) {
    ctx.fillText(String(score), PAD.left - 3, toY(score) + 3)
  }

  const seamX = toX(MORNING_MINS)
  ctx.textAlign = 'center'
  ctx.fillText('9:30', toX(0), H - 4)
  ctx.textAlign = 'right'
  ctx.fillText('11:30', seamX - 3, H - 4)
  ctx.textAlign = 'left'
  ctx.fillText('13:00', seamX + 3, H - 4)
  ctx.textAlign = 'center'
  ctx.fillText('15:00', toX(TRADING_MINS), H - 4)

  if (!series?.length) {
    ctx.fillStyle = 'rgba(255,255,255,0.2)'
    ctx.textAlign = 'center'
    ctx.font = '11px system-ui,sans-serif'
    ctx.fillText('盘中数据加载后显示', PAD.left + cW / 2, PAD.top + cH / 2 + 4)
    return
  }

  const pts = series
    .map((p) => ({ offset: clockMinToTradingOffset(timeToMin(p.time)), score: p.displayScore }))
    .filter((p) => p.offset != null)
    .sort((a, b) => a.offset - b.offset)
  if (!pts.length) return

  const lastScore = pts[pts.length - 1].score

  ctx.beginPath()
  ctx.lineWidth = 2
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'
  pts.forEach((p, i) => {
    if (i === 0) {
      ctx.moveTo(toX(p.offset), toY(p.score))
    } else {
      const prev = pts[i - 1]
      const cpx = (toX(prev.offset) + toX(p.offset)) / 2
      ctx.bezierCurveTo(cpx, toY(prev.score), cpx, toY(p.score), toX(p.offset), toY(p.score))
    }
  })
  ctx.strokeStyle = scoreToColor(lastScore)
  ctx.stroke()

  const last = pts[pts.length - 1]
  const lx = toX(last.offset)
  const ly = toY(last.score)
  ctx.beginPath()
  ctx.arc(lx, ly, 3.5, 0, Math.PI * 2)
  ctx.fillStyle = scoreToColor(last.score)
  ctx.fill()
  ctx.beginPath()
  ctx.arc(lx, ly, 6, 0, Math.PI * 2)
  ctx.strokeStyle = hexToRgba(scoreToColor(last.score), 0.35)
  ctx.lineWidth = 1
  ctx.stroke()
}
