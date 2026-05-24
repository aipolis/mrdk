/**
 * 情绪分享海报（复刻首页 + 视觉精修）
 */

const { getPixelRatio } = require('./device')
const { getDisplayLevel } = require('./theme')
const { drawSteeringGauge } = require('./gaugeDraw')

const POSTER_W = 750
const PAD = 28
const INNER_W = POSTER_W - PAD * 2
const CARD_GAP = 20
const FONT = 'PingFang SC, -apple-system, Helvetica Neue, sans-serif'
const GRID_CELL_H = 132
const GRID_GAP = 12
const DEFAULT_SLOGAN = '不追求每天都有机会，而是帮你识别「不该出手」的日子'

const COLORS = {
  pageTop: '#0c1224',
  pageBottom: '#070b14',
  card: '#141a2e',
  cardHighlight: 'rgba(255,255,255,0.03)',
  gaugeWellTop: '#10182c',
  gaugeWellBottom: '#0a0f1c',
  cell: '#0d1220',
  cellHighlight: 'rgba(255,255,255,0.02)',
  border: 'rgba(255,255,255,0.09)',
  borderLight: 'rgba(255,255,255,0.05)',
  text: '#f9fafb',
  textSoft: '#e5e7eb',
  muted: '#9ca3af',
  dim: '#6b7280',
  red: '#ff4d4f',
  green: '#52c41a',
  white: '#ffffff',
  shadow: 'rgba(0,0,0,0.42)',
  qrBg: '#ffffff'
}

const LEVEL_COLORS = {
  frenzy: '#cf1322',
  climax: '#ff4d4f',
  optimistic: '#ff4d4f',
  neutral: '#faad14',
  caution: '#52c41a',
  cold: '#1890ff'
}

const INVERSE_VALUE_KEYS = new Set(['limitDown', 'break'])

function snap(v) {
  return Math.round(v * 2) / 2
}

function roundRect(ctx, x, y, w, h, r) {
  const radius = Math.min(r, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + radius, y)
  ctx.arcTo(x + w, y, x + w, y + h, radius)
  ctx.arcTo(x + w, y + h, x, y + h, radius)
  ctx.arcTo(x, y + h, x, y, radius)
  ctx.arcTo(x, y, x + w, y, radius)
  ctx.closePath()
}

function drawPageBackground(ctx, w, h) {
  const bg = ctx.createLinearGradient(0, 0, 0, h)
  bg.addColorStop(0, COLORS.pageTop)
  bg.addColorStop(1, COLORS.pageBottom)
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, w, h)

  const glow = ctx.createRadialGradient(w * 0.5, h * 0.18, 0, w * 0.5, h * 0.18, w * 0.55)
  glow.addColorStop(0, 'rgba(255,77,79,0.07)')
  glow.addColorStop(1, 'rgba(255,77,79,0)')
  ctx.fillStyle = glow
  ctx.fillRect(0, 0, w, h)
}

function drawCard(ctx, x, y, w, h, r = 18) {
  roundRect(ctx, x + 2, y + 6, w, h, r)
  ctx.fillStyle = COLORS.shadow
  ctx.fill()

  roundRect(ctx, x, y, w, h, r)
  const cardBg = ctx.createLinearGradient(x, y, x, y + h)
  cardBg.addColorStop(0, '#161d32')
  cardBg.addColorStop(1, COLORS.card)
  ctx.fillStyle = cardBg
  ctx.fill()

  roundRect(ctx, x + 1, y + 1, w - 2, h * 0.42, r - 1)
  ctx.fillStyle = COLORS.cardHighlight
  ctx.fill()

  ctx.strokeStyle = COLORS.border
  ctx.lineWidth = 1
  roundRect(ctx, x + 0.5, y + 0.5, w - 1, h - 1, r)
  ctx.stroke()
}

function drawSectionHead(ctx, x, y, w, title, meta) {
  ctx.textBaseline = 'alphabetic'
  ctx.textAlign = 'left'
  ctx.fillStyle = COLORS.text
  ctx.font = `600 30px ${FONT}`
  ctx.fillText(title, x, y)

  if (meta) {
    ctx.textAlign = 'right'
    ctx.fillStyle = COLORS.dim
    ctx.font = `400 22px ${FONT}`
    ctx.fillText(meta, x + w, y)
  }
}

function drawAccentLine(ctx, cx, y, color) {
  ctx.strokeStyle = color || COLORS.red
  ctx.lineWidth = 3
  ctx.lineCap = 'round'
  ctx.beginPath()
  ctx.moveTo(cx - 40, y)
  ctx.lineTo(cx + 40, y)
  ctx.stroke()
}

function wrapText(ctx, text, maxWidth) {
  const chars = String(text || '').split('')
  const lines = []
  let line = ''
  chars.forEach(ch => {
    const test = line + ch
    if (ctx.measureText(test).width > maxWidth && line) {
      lines.push(line)
      line = ch
    } else {
      line = test
    }
  })
  if (line) lines.push(line)
  return lines
}

function getYesterdayCells(sections) {
  const sec = (sections || []).find(s => s.id === 'yesterday')
  if (!sec) return []
  const cells = []
  ;(sec.rows || []).forEach(row => {
    ;(row || []).forEach(cell => cells.push(cell))
  })
  return cells.slice(0, 9)
}

function cellValueColor(key) {
  if (key === 'volume') return COLORS.textSoft
  if (key === 'advance') return COLORS.red
  if (INVERSE_VALUE_KEYS.has(key)) return COLORS.green
  return COLORS.red
}

function cellPrevText(cell) {
  const prev = cell.prev != null ? String(cell.prev) : (cell.yesterday != null ? String(cell.yesterday) : '')
  if (!prev || prev === '--') return ''
  return `前 ${prev}`
}

function loadCanvasImage(canvas, src) {
  return new Promise((resolve, reject) => {
    if (!src) {
      reject(new Error('empty image'))
      return
    }
    const img = canvas.createImage()
    img.onload = () => resolve(img)
    img.onerror = err => reject(err || new Error('image load fail'))
    img.src = src
  })
}

function calcTopHeaderHeight() {
  return snap(20 + 44 + 16)
}

function calcFooterHeight(ctx, w, slogan) {
  const textW = w - 56 - 96 - 22 - 28
  ctx.font = `400 22px ${FONT}`
  const lines = wrapText(ctx, slogan || DEFAULT_SLOGAN, textW).slice(0, 2)
  const blockH = Math.max(96, lines.length * 28 + 12)
  return snap(20 + blockH + 36)
}

function calcPosterHeight(data) {
  const slogan = data.slogan || DEFAULT_SLOGAN
  const mockCtx = {
    font: '',
    measureText(s) {
      return { width: [...String(s)].length * 22 }
    }
  }
  const headerH = calcTopHeaderHeight()
  const gaugeH = 28 + 44 + 40 + 44 + 292 + 28
  const gridRows = Math.ceil(getYesterdayCells(data.indicatorSections).length / 3) || 3
  const gridH = 28 + 44 + gridRows * (GRID_CELL_H + GRID_GAP) - GRID_GAP + 28
  const footerH = calcFooterHeight(mockCtx, INNER_W, slogan)
  return snap(PAD + headerH + CARD_GAP + gaugeH + CARD_GAP + gridH + CARD_GAP + footerH + PAD + 8)
}

function drawTopBrand(ctx, x, y, w) {
  const h = calcTopHeaderHeight()

  ctx.textAlign = 'center'
  ctx.textBaseline = 'alphabetic'
  ctx.fillStyle = COLORS.text
  ctx.font = `700 40px ${FONT}`
  ctx.fillText('明日当空', x + w / 2, y + 40)

  ctx.strokeStyle = COLORS.borderLight
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(x, y + h - 4)
  ctx.lineTo(x + w, y + h - 4)
  ctx.stroke()

  return h
}

function drawGaugeWell(ctx, x, y, w, h) {
  roundRect(ctx, x, y, w, h, 14)
  const grad = ctx.createLinearGradient(x, y, x, y + h)
  grad.addColorStop(0, COLORS.gaugeWellTop)
  grad.addColorStop(1, COLORS.gaugeWellBottom)
  ctx.fillStyle = grad
  ctx.fill()
  ctx.strokeStyle = COLORS.borderLight
  ctx.lineWidth = 1
  ctx.stroke()

  const innerGlow = ctx.createRadialGradient(x + w / 2, y + h * 0.72, 0, x + w / 2, y + h * 0.72, w * 0.42)
  innerGlow.addColorStop(0, 'rgba(255,77,79,0.06)')
  innerGlow.addColorStop(1, 'rgba(255,77,79,0)')
  ctx.fillStyle = innerGlow
  ctx.fillRect(x, y, w, h)
}

function drawGaugeCard(ctx, x, y, w, data) {
  const score = Number(
    data.displayScore != null && data.displayScore !== ''
      ? data.displayScore
      : (data.score || 0)
  )
  const level = getDisplayLevel(score)
  const levelColor = LEVEL_COLORS[data.levelClass] || level.color || COLORS.red
  const gaugeH = 292
  const h = 28 + 44 + 40 + 44 + gaugeH + 28

  drawCard(ctx, x, y, w, h)
  drawSectionHead(ctx, x + 28, y + 40, w - 56, '市场情绪', data.generatedAt || '昨日 15:00 更新')

  const levelY = y + 92
  ctx.textAlign = 'center'
  ctx.textBaseline = 'alphabetic'
  ctx.fillStyle = levelColor
  ctx.font = `700 32px ${FONT}`
  ctx.fillText(data.levelLabel || level.label, x + w / 2, levelY)

  const desc = (data.positionDesc || '').replace(/。$/, '')
  ctx.fillStyle = COLORS.muted
  ctx.font = `400 24px ${FONT}`
  const descLines = wrapText(ctx, desc, w - 80)
  ctx.fillText(descLines[0] || desc, x + w / 2, levelY + 34)
  drawAccentLine(ctx, x + w / 2, levelY + 48, levelColor)

  const gx = x + 28
  const gy = y + 132
  const gw = w - 56

  ctx.save()
  drawGaugeWell(ctx, gx, gy, gw, gaugeH)
  roundRect(ctx, gx, gy, gw, gaugeH, 14)
  ctx.clip()
  ctx.translate(gx, gy)
  drawSteeringGauge(ctx, gw, gaugeH, score, 'dark', { skipClear: true })

  const hubY = gaugeH * 0.58
  ctx.shadowColor = `${levelColor}55`
  ctx.shadowBlur = 18
  ctx.fillStyle = levelColor
  ctx.font = `700 92px ${FONT}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(String(score), gw / 2, hubY)
  ctx.shadowBlur = 0

  ctx.fillStyle = COLORS.muted
  ctx.font = `500 24px ${FONT}`
  ctx.fillText('情绪分', gw / 2, hubY + 54)
  ctx.restore()

  return h
}

function drawGridCell(ctx, cx, cy, cellW, cellH, cell) {
  roundRect(ctx, cx, cy, cellW, cellH, 14)
  const cellBg = ctx.createLinearGradient(cx, cy, cx, cy + cellH)
  cellBg.addColorStop(0, '#111827')
  cellBg.addColorStop(1, COLORS.cell)
  ctx.fillStyle = cellBg
  ctx.fill()
  roundRect(ctx, cx + 1, cy + 1, cellW - 2, cellH * 0.45, 13)
  ctx.fillStyle = COLORS.cellHighlight
  ctx.fill()
  ctx.strokeStyle = COLORS.borderLight
  ctx.lineWidth = 1
  roundRect(ctx, cx + 0.5, cy + 0.5, cellW - 1, cellH - 1, 14)
  ctx.stroke()

  const val = String(cell.displayValue || cell.value || '--')
  const valColor = cellValueColor(cell.key)
  const arrow = cell.trendArrow || ''
  const arrowColor = cell.trendGood === true
    ? COLORS.red
    : (cell.trendGood === false ? COLORS.green : COLORS.muted)

  ctx.font = `700 32px ${FONT}`
  const valW = ctx.measureText(val).width
  let arrowW = 0
  if (arrow) {
    ctx.font = `600 24px ${FONT}`
    arrowW = ctx.measureText(arrow).width + 6
    ctx.font = `700 32px ${FONT}`
  }

  const rowY = cy + 38
  const startX = cx + cellW / 2 - (valW + arrowW) / 2
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = valColor
  ctx.font = `700 32px ${FONT}`
  ctx.fillText(val, startX, rowY)

  if (arrow) {
    ctx.fillStyle = arrowColor
    ctx.font = `600 24px ${FONT}`
    ctx.fillText(arrow, startX + valW + 4, rowY)
  }

  ctx.textAlign = 'center'
  ctx.fillStyle = COLORS.muted
  ctx.font = `400 20px ${FONT}`
  ctx.fillText((cell.label || '').slice(0, 8), cx + cellW / 2, cy + 72)

  const prevText = cellPrevText(cell)
  if (prevText) {
    ctx.fillStyle = cell.key === 'advance' ? COLORS.red : COLORS.dim
    ctx.font = `400 18px ${FONT}`
    ctx.fillText(prevText, cx + cellW / 2, cy + 98)
  }
}

function drawGridCard(ctx, x, y, w, data) {
  const cells = getYesterdayCells(data.indicatorSections)
  const yesterdaySec = (data.indicatorSections || []).find(s => s.id === 'yesterday')
  const gridTitle = (yesterdaySec && yesterdaySec.title) || '昨日情绪概览'
  const gridMeta = (yesterdaySec && yesterdaySec.meta) || ''
  const cellW = (w - 56 - GRID_GAP * 2) / 3
  const gridRows = Math.ceil(cells.length / 3) || 3
  const h = 28 + 44 + gridRows * (GRID_CELL_H + GRID_GAP) - GRID_GAP + 28

  drawCard(ctx, x, y, w, h)
  drawSectionHead(ctx, x + 28, y + 40, w - 56, gridTitle, gridMeta)

  const cy = y + 68
  cells.forEach((cell, idx) => {
    const col = idx % 3
    const row = Math.floor(idx / 3)
    const cx = x + 28 + col * (cellW + GRID_GAP)
    drawGridCell(ctx, cx, cy + row * (GRID_CELL_H + GRID_GAP), cellW, GRID_CELL_H, cell)
  })

  return h
}

function drawFooter(ctx, x, y, w, data, qrImage) {
  const slogan = data.slogan || DEFAULT_SLOGAN
  const h = calcFooterHeight(ctx, w - 56, slogan)
  drawCard(ctx, x, y, w, h)

  const qrSize = 96
  const qrX = x + 28
  const blockTop = y + 20
  const qrY = blockTop + 4

  roundRect(ctx, qrX - 3, qrY - 3, qrSize + 6, qrSize + 6, 12)
  ctx.fillStyle = COLORS.qrBg
  ctx.fill()
  ctx.strokeStyle = 'rgba(255,255,255,0.1)'
  ctx.lineWidth = 1
  ctx.stroke()

  if (qrImage) {
    ctx.save()
    roundRect(ctx, qrX, qrY, qrSize, qrSize, 8)
    ctx.clip()
    ctx.drawImage(qrImage, qrX, qrY, qrSize, qrSize)
    ctx.restore()
  }

  const textX = qrX + qrSize + 22
  const textW = w - (textX - x) - 28

  ctx.textAlign = 'left'
  ctx.textBaseline = 'alphabetic'
  ctx.fillStyle = COLORS.muted
  ctx.font = `400 22px ${FONT}`
  const sloganLines = wrapText(ctx, slogan, textW).slice(0, 2)
  const textBlockH = sloganLines.length * 28
  const textStartY = blockTop + (qrSize + 8 - textBlockH) / 2 + 22
  sloganLines.forEach((line, i) => {
    ctx.fillText(line, textX, textStartY + i * 28)
  })

  ctx.fillStyle = COLORS.dim
  ctx.font = `400 17px ${FONT}`
  ctx.textAlign = 'center'
  ctx.fillText('长按识别小程序码 · 数据仅供参考，不构成投资建议', x + w / 2, y + h - 14)

  return h
}

function drawPoster(ctx, width, height, data, qrImage) {
  drawPageBackground(ctx, width, height)

  let y = PAD + 4
  const cardW = INNER_W

  y += drawTopBrand(ctx, PAD, y, cardW) + CARD_GAP
  y += drawGaugeCard(ctx, PAD, y, cardW, data) + CARD_GAP
  y += drawGridCard(ctx, PAD, y, cardW, data) + CARD_GAP
  drawFooter(ctx, PAD, y, cardW, data, qrImage)
}

function createOffscreen(w, h) {
  const dpr = getPixelRatio()
  const pxW = Math.floor(w * dpr)
  const pxH = Math.floor(h * dpr)
  const canvas = wx.createOffscreenCanvas({ type: '2d', width: pxW, height: pxH })
  const ctx = canvas.getContext('2d')
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.scale(pxW / w, pxH / h)
  return { canvas, ctx, dpr, width: w, height: h, pxW, pxH }
}

function exportPoster(canvas) {
  return new Promise((resolve, reject) => {
    wx.canvasToTempFilePath({
      canvas,
      x: 0,
      y: 0,
      width: canvas.width,
      height: canvas.height,
      destWidth: canvas.width,
      destHeight: canvas.height,
      fileType: 'png',
      quality: 1,
      success: res => {
        if (res.tempFilePath) resolve(res.tempFilePath)
        else reject(new Error('empty poster path'))
      },
      fail: reject
    })
  })
}

function generateSharePoster(data, qrLocalPath) {
  const height = Math.max(1200, calcPosterHeight(data))
  const { canvas, ctx, width } = createOffscreen(POSTER_W, height)

  return loadCanvasImage(canvas, qrLocalPath).catch(() => null).then(qrImage => {
    drawPoster(ctx, width, height, data, qrImage)
    return exportPoster(canvas)
  })
}

module.exports = {
  generateSharePoster,
  POSTER_W,
  calcPosterHeight
}
