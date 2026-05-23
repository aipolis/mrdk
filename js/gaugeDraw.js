/**
 * 情绪分仪表盘（浏览器 ES Module）
 * 弧从左下(0分) → 经顶部(50分) → 右下(100分)
 */

const START_ANGLE = Math.PI * 3 / 4
const SWEEP = Math.PI * 3 / 2

function angleAtScore(score) {
  const s = Math.max(0, Math.min(100, score))
  return START_ANGLE + (s / 100) * SWEEP
}

function scoreAtSegment(i, segTotal) {
  return ((i + 0.5) / segTotal) * 100
}

function lerpColor(c1, c2, t) {
  const parse = (c) => {
    const h = c.replace('#', '')
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]
  }
  const [r1, g1, b1] = parse(c1)
  const [r2, g2, b2] = parse(c2)
  return `rgb(${Math.round(r1 + (r2 - r1) * t)},${Math.round(g1 + (g2 - g1) * t)},${Math.round(b1 + (b2 - b1) * t)})`
}

function colorAt(ratio, stops) {
  const t = Math.max(0, Math.min(1, ratio))
  let i = 0
  while (i < stops.length - 1 && t > stops[i + 1].pos) i++
  const a = stops[i]
  const b = stops[Math.min(i + 1, stops.length - 1)]
  if (a.pos === b.pos) return a.color
  return lerpColor(a.color, b.color, (t - a.pos) / (b.pos - a.pos))
}

function segmentFillColor(scoreVal, isActive, theme) {
  const isLight = theme === 'light'
  if (!isActive) {
    if (scoreVal < 40) return isLight ? '#d1d5db' : '#3d4659'
    return isLight ? '#e5e7eb' : '#2a3348'
  }
  if (scoreVal < 40) return '#8b95a5'
  if (scoreVal <= 80) {
    const t = (scoreVal - 40) / 40
    return colorAt(t, [
      { pos: 0, color: '#52c41a' },
      { pos: 0.4, color: '#a0d911' },
      { pos: 0.7, color: '#faad14' },
      { pos: 1, color: '#ff7a45' },
    ])
  }
  const t = (scoreVal - 80) / 20
  return colorAt(t, [
    { pos: 0, color: '#ff7a45' },
    { pos: 0.5, color: '#ff4d4f' },
    { pos: 1, color: '#cf1322' },
  ])
}

export function drawSteeringGauge(ctx, width, height, score, theme = 'dark', options = {}) {
  const skipClear = options.skipClear
  const s = Math.max(0, Math.min(100, score || 0))
  const snap = (v) => Math.round(v * 2) / 2
  const cx = snap(width / 2)
  const cy = snap(height * 0.62)
  const radius = snap(Math.min(width * 0.4, height * 0.46))
  const bandW = options.bandWidth != null
    ? options.bandWidth
    : Math.max(14, Math.round(radius * 0.16))
  const bandScale = bandW / 16
  const isLight = theme === 'light'

  if (!skipClear) ctx.clearRect(0, 0, width, height)

  const strokeArc = (from, to, color, lineW, cap) => {
    ctx.beginPath()
    ctx.arc(cx, cy, radius, from, to, false)
    ctx.lineWidth = lineW
    ctx.lineCap = cap || 'butt'
    ctx.strokeStyle = color
    ctx.stroke()
  }

  strokeArc(START_ANGLE, START_ANGLE + SWEEP, isLight ? '#e5e7eb' : '#232b3e', bandW + Math.round(8 * bandScale), 'round')

  const segTotal = 40
  const gap = 0.012
  for (let i = 0; i < segTotal; i++) {
    const a0 = START_ANGLE + (i / segTotal) * SWEEP + gap
    const a1 = START_ANGLE + ((i + 1) / segTotal) * SWEEP - gap
    const segScore = scoreAtSegment(i, segTotal)
    strokeArc(a0, a1, segmentFillColor(segScore, segScore <= s, theme), bandW, 'butt')
  }

  const pointerAngle = angleAtScore(s)
  const tipR = radius + bandW / 2 + 1
  const tipX = cx + tipR * Math.cos(pointerAngle)
  const tipY = cy + tipR * Math.sin(pointerAngle)
  const baseR = radius - bandW / 2 - Math.round(8 * bandScale)
  const baseX = cx + baseR * Math.cos(pointerAngle)
  const baseY = cy + baseR * Math.sin(pointerAngle)
  const pointerColor = segmentFillColor(s, true, theme)
  const px = Math.cos(pointerAngle)
  const py = Math.sin(pointerAngle)
  const nx = -py
  const ny = px
  const pw = 6 * bandScale
  const pl = 9 * bandScale

  ctx.beginPath()
  ctx.moveTo(tipX, tipY)
  ctx.lineTo(baseX + nx * pw - px * pl, baseY + ny * pw - py * pl)
  ctx.lineTo(baseX - nx * pw - px * pl, baseY - ny * pw - py * pl)
  ctx.closePath()
  ctx.fillStyle = pointerColor
  ctx.fill()

  const tipOuter = Math.max(4, 5 * bandScale)
  const tipInner = Math.max(2.5, 3 * bandScale)
  ctx.beginPath()
  ctx.arc(tipX, tipY, tipOuter, 0, Math.PI * 2)
  ctx.fillStyle = '#ffffff'
  ctx.fill()
  ctx.beginPath()
  ctx.arc(tipX, tipY, tipInner, 0, Math.PI * 2)
  ctx.fillStyle = pointerColor
  ctx.fill()
}
