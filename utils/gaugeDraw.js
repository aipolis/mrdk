/**
 * 情绪分仪表盘
 * 弧从左下(0分) → 经顶部(50分) → 右下(100分)，分数与指针位置线性对应
 * 0-40 灰 | 40-80 绿黄橙 | 80-100 渐变大红
 */

const START_ANGLE = Math.PI * 3 / 4   // 左端 0 分
const SWEEP = Math.PI * 3 / 2         // 顺时针扫过 270°

function angleAtScore(score) {
  const s = Math.max(0, Math.min(100, score))
  return START_ANGLE + (s / 100) * SWEEP
}

function scoreAtSegment(i, segTotal) {
  return ((i + 0.5) / segTotal) * 100
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

function drawSteeringGauge(ctx, width, height, score, theme, options) {
  const isLight = theme === 'light'
  const skipClear = options && options.skipClear
  const s = Math.max(0, Math.min(100, score || 0))
  const snap = v => Math.round(v * 2) / 2
  const cx = snap(width / 2)
  const cy = snap(height * 0.62)
  const radius = snap(Math.min(width * 0.4, height * 0.46))
  const bandW = 16

  if (!skipClear) {
    ctx.clearRect(0, 0, width, height)
  }

  const strokeArc = (from, to, color, lineW, cap) => {
    ctx.beginPath()
    ctx.arc(cx, cy, radius, from, to, false)
    ctx.lineWidth = lineW
    ctx.lineCap = cap || 'butt'
    ctx.strokeStyle = color
    ctx.stroke()
  }

  strokeArc(START_ANGLE, START_ANGLE + SWEEP, isLight ? '#e5e7eb' : '#232b3e', bandW + 8, 'round')

  const segTotal = 40
  const gap = 0.012

  for (let i = 0; i < segTotal; i++) {
    const a0 = START_ANGLE + (i / segTotal) * SWEEP + gap
    const a1 = START_ANGLE + ((i + 1) / segTotal) * SWEEP - gap
    const segScore = scoreAtSegment(i, segTotal)
    const isActive = segScore <= s
    strokeArc(a0, a1, segmentFillColor(segScore, isActive, theme), bandW, 'butt')
  }

  ctx.beginPath()
  ctx.arc(cx, cy, radius - bandW * 0.75, 0, Math.PI * 2)
  ctx.strokeStyle = isLight ? 'rgba(15, 23, 42, 0.06)' : 'rgba(255, 255, 255, 0.05)'
  ctx.lineWidth = 1
  ctx.stroke()

  for (let i = 0; i <= segTotal; i++) {
    const ang = START_ANGLE + (i / segTotal) * SWEEP
    const tickScore = (i / segTotal) * 100
    const inner = radius - bandW / 2 - 2
    const outer = radius + bandW / 2 + (i % 10 === 0 ? 5 : 2)
    ctx.beginPath()
    ctx.moveTo(cx + inner * Math.cos(ang), cy + inner * Math.sin(ang))
    ctx.lineTo(cx + outer * Math.cos(ang), cy + outer * Math.sin(ang))
    ctx.strokeStyle = tickScore <= s
      ? (isLight ? 'rgba(15, 23, 42, 0.2)' : 'rgba(255,255,255,0.15)')
      : (isLight ? 'rgba(15, 23, 42, 0.08)' : 'rgba(255,255,255,0.05)')
    ctx.lineWidth = 1
    ctx.stroke()
  }

  const pointerAngle = angleAtScore(s)
  const tipR = radius + bandW / 2 + 1
  const tipX = cx + tipR * Math.cos(pointerAngle)
  const tipY = cy + tipR * Math.sin(pointerAngle)
  const baseR = radius - bandW / 2 - 8
  const baseX = cx + baseR * Math.cos(pointerAngle)
  const baseY = cy + baseR * Math.sin(pointerAngle)
  const pointerColor = segmentFillColor(s, true, theme)

  const px = Math.cos(pointerAngle)
  const py = Math.sin(pointerAngle)
  const nx = -py
  const ny = px
  const wing = 6
  const back = 9

  ctx.beginPath()
  ctx.moveTo(tipX, tipY)
  ctx.lineTo(baseX + nx * wing - px * back, baseY + ny * wing - py * back)
  ctx.lineTo(baseX - nx * wing - px * back, baseY - ny * wing - py * back)
  ctx.closePath()
  ctx.fillStyle = pointerColor
  ctx.fill()

  ctx.beginPath()
  ctx.arc(tipX, tipY, 5, 0, Math.PI * 2)
  ctx.fillStyle = '#ffffff'
  ctx.fill()
  ctx.beginPath()
  ctx.arc(tipX, tipY, 3, 0, Math.PI * 2)
  ctx.fillStyle = pointerColor
  ctx.fill()
}

function colorAt(ratio, stops) {
  const t = Math.max(0, Math.min(1, ratio))
  let i = 0
  while (i < stops.length - 1 && t > stops[i + 1].pos) i++
  const a = stops[i]
  const b = stops[Math.min(i + 1, stops.length - 1)]
  if (a.pos === b.pos) return a.color
  const f = (t - a.pos) / (b.pos - a.pos)
  return lerpColor(a.color, b.color, f)
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

module.exports = { drawSteeringGauge, segmentFillColor, angleAtScore }
