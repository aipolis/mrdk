/** 盘中分时走势图：canvas 渲染 */

const SESSION_START = 9 * 60 + 30   // 570 min
const SESSION_END   = 15 * 60        // 900 min
const SESSION_MINS  = SESSION_END - SESSION_START  // 330

function timeToMin(t) {
  // t: "09:30" or "0930" or "HH:MM"
  const s = String(t || '').replace(':', '')
  if (s.length < 4) return null
  return parseInt(s.slice(0, 2), 10) * 60 + parseInt(s.slice(2, 4), 10)
}

function scoreToColor(score) {
  if (score >= 60) return '#f87171'   // red – strong
  if (score >= 50) return '#fbbf24'   // yellow – neutral
  if (score >= 30) return '#38bdf8'   // blue – cold
  return '#6b7280'                     // gray – empty
}

/** hex(#rrggbb) → rgba，用于半透明光晕 */
function hexToRgba(hex, alpha) {
  const h = String(hex).replace('#', '')
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
}

function bandColor(score) {
  if (score >= 60) return 'rgba(248,113,113,0.07)'
  if (score >= 50) return 'rgba(251,191,36,0.07)'
  if (score >= 30) return 'rgba(56,189,248,0.07)'
  return 'rgba(107,114,128,0.07)'
}

export function drawIntradayChart(canvas, series) {
  if (!canvas) return
  const dpr = window.devicePixelRatio || 1
  const W = canvas.offsetWidth || 320
  const H = canvas.offsetHeight || 90
  canvas.width  = W * dpr
  canvas.height = H * dpr
  const ctx = canvas.getContext('2d')
  ctx.scale(dpr, dpr)

  const PAD = { top: 8, right: 12, bottom: 20, left: 28 }
  const cW = W - PAD.left - PAD.right
  const cH = H - PAD.top  - PAD.bottom

  ctx.clearRect(0, 0, W, H)

  // ── background bands ────────────────────────────────────────
  const bands = [
    { lo: 60, hi: 100, color: 'rgba(248,113,113,0.06)' },
    { lo: 50, hi: 60,  color: 'rgba(251,191,36,0.06)'  },
    { lo: 30, hi: 50,  color: 'rgba(56,189,248,0.06)'  },
    { lo: 0,  hi: 30,  color: 'rgba(107,114,128,0.06)' },
  ]
  for (const b of bands) {
    const y1 = PAD.top + cH * (1 - b.hi / 100)
    const y2 = PAD.top + cH * (1 - b.lo / 100)
    ctx.fillStyle = b.color
    ctx.fillRect(PAD.left, y1, cW, y2 - y1)
  }

  // ── grid lines ──────────────────────────────────────────────
  ctx.strokeStyle = 'rgba(255,255,255,0.06)'
  ctx.lineWidth = 1
  for (const score of [30, 50, 60]) {
    const y = PAD.top + cH * (1 - score / 100)
    ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + cW, y); ctx.stroke()
  }

  // ── Y axis labels ───────────────────────────────────────────
  ctx.fillStyle = 'rgba(255,255,255,0.3)'
  ctx.font = `${9 * (dpr < 2 ? 1 : 0.8)}px system-ui,sans-serif`
  ctx.textAlign = 'right'
  for (const score of [30, 50, 60]) {
    const y = PAD.top + cH * (1 - score / 100)
    ctx.fillText(String(score), PAD.left - 3, y + 3)
  }

  // ── X axis labels ───────────────────────────────────────────
  ctx.textAlign = 'center'
  for (const [label, min] of [['9:30', SESSION_START], ['11:30', 11*60+30], ['13:00', 13*60], ['15:00', SESSION_END]]) {
    const x = PAD.left + ((min - SESSION_START) / SESSION_MINS) * cW
    ctx.fillText(label, x, H - 4)
  }

  if (!series?.length) {
    ctx.fillStyle = 'rgba(255,255,255,0.2)'
    ctx.textAlign = 'center'
    ctx.font = '11px system-ui,sans-serif'
    ctx.fillText('盘中数据加载后显示', PAD.left + cW / 2, PAD.top + cH / 2 + 4)
    return
  }

  // ── filter points within session ────────────────────────────
  const pts = series
    .map(p => ({ min: timeToMin(p.time), score: p.displayScore }))
    .filter(p => p.min !== null && p.min >= SESSION_START && p.min <= SESSION_END)
  if (!pts.length) return

  const toX = min => PAD.left + ((min - SESSION_START) / SESSION_MINS) * cW
  const toY = s   => PAD.top  + cH * (1 - Math.max(0, Math.min(100, s)) / 100)

  const lastScore = pts[pts.length - 1].score

  // ── smooth line ──────────────────────────────────────────────
  ctx.beginPath()
  ctx.lineWidth = 2
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'
  pts.forEach((p, i) => {
    if (i === 0) {
      ctx.moveTo(toX(p.min), toY(p.score))
    } else {
      // catmull-rom 平滑
      const prev = pts[i - 1]
      const cpx = (toX(prev.min) + toX(p.min)) / 2
      ctx.bezierCurveTo(cpx, toY(prev.score), cpx, toY(p.score), toX(p.min), toY(p.score))
    }
  })
  ctx.strokeStyle = scoreToColor(lastScore)
  ctx.stroke()

  // ── live dot ────────────────────────────────────────────────
  const last = pts[pts.length - 1]
  const lx = toX(last.min), ly = toY(last.score)
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
