/**
 * 分享海报：手机竖屏适配（格言 + 表盘 + 昨日/盘中 + 页脚）
 */
import { drawSteeringGauge } from './gaugeDraw.js?v=20260531a'
import { getDisplayLevel, formatHeaderDate, HOME_QUOTE } from './theme.js?v=20260531a'
import { scoreToLongkongState, LONGKONG_STATE_STEPS, buildRiskCopy } from './longkongState.js?v=20260604c'
import { normalizeSections } from './indicators.js?v=20260604d'
import { drawQrCode } from './qrDraw.js?v=20260531a'

export const POSTER_W = 1080
const SCALE = POSTER_W / 750
const sc = (n) => Math.round(n * SCALE)

const PAD = sc(28)
const INNER_W = POSTER_W - PAD * 2
const CARD_GAP = sc(20)
const GRID_CELL_H = sc(132)
const GRID_GAP = sc(12)
const FONT = 'PingFang SC, -apple-system, BlinkMacSystemFont, sans-serif'

const COLORS = {
  pageTop: '#0c1224',
  pageBottom: '#070b14',
  card: '#141a2e',
  gaugeWellTop: '#10182c',
  gaugeWellBottom: '#0a0f1c',
  cell: '#0d1220',
  border: 'rgba(255,255,255,0.09)',
  borderLight: 'rgba(255,255,255,0.05)',
  text: '#f9fafb',
  textSoft: '#e5e7eb',
  muted: '#9ca3af',
  dim: '#6b7280',
  red: '#ff4d4f',
  green: '#52c41a',
  shadow: 'rgba(0,0,0,0.42)',
}

const LEVEL_COLORS = {
  frenzy: '#cf1322',
  climax: '#ff4d4f',
  optimistic: '#ff4d4f',
  neutral: '#faad14',
  caution: '#52c41a',
  cold: '#1890ff',
}

const LEVEL_LIGHT = {
  frenzy:    { bg: 'rgba(248,113,113,0.10)', border: 'rgba(248,113,113,0.45)', dot: '#f87171' },
  climax:    { bg: 'rgba(248,113,113,0.10)', border: 'rgba(248,113,113,0.45)', dot: '#f87171' },
  optimistic:{ bg: 'rgba(248,113,113,0.10)', border: 'rgba(248,113,113,0.45)', dot: '#f87171' },
  neutral:   { bg: 'rgba(251,191,36,0.10)',  border: 'rgba(251,191,36,0.45)',  dot: '#fbbf24' },
  caution:   { bg: 'rgba(74,222,128,0.08)',  border: 'rgba(74,222,128,0.40)',  dot: '#4ade80' },
  weak:      { bg: 'rgba(56,189,248,0.10)',  border: 'rgba(56,189,248,0.45)',  dot: '#38bdf8' },
  cold:      { bg: 'rgba(96,165,250,0.10)',  border: 'rgba(96,165,250,0.45)',  dot: '#60a5fa' },
}

const INVERSE_VALUE_KEYS = new Set(['limitDown', 'break', 'limitDownLive', 'breakLive'])

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

function wrapText(ctx, text, maxWidth) {
  const chars = String(text || '').split('')
  const lines = []
  let line = ''
  chars.forEach((ch) => {
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

function getSections(data) {
  return normalizeSections(data.indicatorSections || data.sections || [])
}

/** 海报仅保留昨日概览、盘中实时（不含外围、竞价、趋势图） */
function getPosterSections(data) {
  const keep = new Set(['yesterday', 'intraday'])
  return getSections(data).filter((sec) => keep.has(sec.id))
}

function formatQuote() {
  return /[。！？；…]$/.test(HOME_QUOTE) ? HOME_QUOTE : `${HOME_QUOTE}。`
}

function cellValueColor(key) {
  if (key === 'volume') return COLORS.textSoft
  if (key === 'advance') return COLORS.red
  if (INVERSE_VALUE_KEYS.has(key)) return COLORS.green
  return COLORS.red
}

function cellPrevText(cell, sectionId) {
  const prev = cell.prev != null ? String(cell.prev) : ''
  if (!prev || prev === '--') return ''
  return `昨 ${prev}`
}

function drawPageBackground(ctx, w, h) {
  const bg = ctx.createLinearGradient(0, 0, 0, h)
  bg.addColorStop(0, COLORS.pageTop)
  bg.addColorStop(1, COLORS.pageBottom)
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, w, h)
}

function drawCard(ctx, x, y, w, h, r = sc(18)) {
  roundRect(ctx, x + 2, y + 6, w, h, r)
  ctx.fillStyle = COLORS.shadow
  ctx.fill()
  roundRect(ctx, x, y, w, h, r)
  ctx.fillStyle = COLORS.card
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
  ctx.font = `600 ${sc(30)}px ${FONT}`
  ctx.fillText(title || '', x, y)
  if (meta) {
    ctx.textAlign = 'right'
    ctx.fillStyle = COLORS.dim
    ctx.font = `400 ${sc(22)}px ${FONT}`
    ctx.fillText(meta, x + w, y)
  }
}

// 布局常量（以 sc 为单位）：
//   pill top=28, pill h=40, pill bottom=68
//   quote baseline = pill_bottom + gap_to_cap(20) + cap_h(19) = 107 → 用 sc(108)
//   quote line height = sc(38)
//   gap quote_bottom → author_top = sc(16)，author cap ≈ sc(14)
//   author baseline = quote_last_baseline + sc(38) + sc(16) + sc(14) = last + sc(68)
//     — 但统一写成 quoteStartY + lineCount*sc(38) + sc(20)
//   bottom pad = sc(32)
const _QT = {
  pillTop: sc(28), pillH: sc(40),
  quoteBaselineOffset: sc(108),  // from card y to first quote text baseline
  lineH: sc(38),
  authorGap: sc(20),             // from last quote baseline to author baseline
  bottomPad: sc(32),
}

function calcQuoteCardHeight(quoteLineCount = 1) {
  return _QT.quoteBaselineOffset + quoteLineCount * _QT.lineH + _QT.authorGap + sc(28)
}

function drawQuoteCard(ctx, x, y, w, quote) {
  ctx.font = `500 ${sc(26)}px ${FONT}`
  const lines = wrapText(ctx, quote, w - sc(80)).slice(0, 2)
  const h = calcQuoteCardHeight(lines.length)
  drawCard(ctx, x, y, w, h)

  // 「与君共勉」胶囊
  const pillW = sc(100)
  roundRect(ctx, x + sc(28), y + _QT.pillTop, pillW, _QT.pillH, sc(20))
  ctx.fillStyle = 'rgba(255,77,79,0.15)'
  ctx.fill()
  ctx.strokeStyle = 'rgba(255,77,79,0.35)'
  ctx.lineWidth = 1
  ctx.stroke()
  ctx.fillStyle = COLORS.red
  ctx.font = `600 ${sc(22)}px ${FONT}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('与君共勉', x + sc(28) + pillW / 2, y + _QT.pillTop + _QT.pillH / 2)

  // 引言正文
  ctx.fillStyle = COLORS.text
  ctx.font = `500 ${sc(26)}px ${FONT}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'alphabetic'
  const quoteBaseY = y + _QT.quoteBaselineOffset
  lines.forEach((line, i) => {
    ctx.fillText(line, x + w / 2, quoteBaseY + i * _QT.lineH)
  })

  // 作者（右对齐，在最后一行 baseline 下方 authorGap）
  const authorY = quoteBaseY + lines.length * _QT.lineH + _QT.authorGap
  ctx.fillStyle = COLORS.dim
  ctx.font = `400 ${sc(20)}px ${FONT}`
  ctx.textAlign = 'right'
  ctx.fillText('—— 养家心法', x + w - sc(40), authorY)
  ctx.textAlign = 'center'

  return h
}

function calcGaugeCardHeight(data) {
  let h = sc(28) + sc(44) + sc(40) + sc(44) + sc(100) + sc(292) + sc(28)
  if (data.scoreMode === 'live' && data.baselineScore != null) h += sc(28)
  if (data.emptyWarning) h += sc(44)
  return h
}

function drawGaugeCard(ctx, x, y, w, data) {
  const score = Number(data.displayScore != null ? data.displayScore : (data.score || 0))
  const level = getDisplayLevel(score)
  const levelColor = LEVEL_COLORS[data.levelClass] || level.color
  const gaugeH = sc(292)
  const h = calcGaugeCardHeight(data)

  const riskCopy = buildRiskCopy(data)
  const positionDesc = (riskCopy?.desc || data.positionDesc || '').replace(/。$/, '')
  const lk = scoreToLongkongState(score, !!data.emptyWarning)

  drawCard(ctx, x, y, w, h)
  drawSectionHead(ctx, x + sc(28), y + sc(40), w - sc(56), '市场情绪', data.generatedAtLabel || data.generatedAt || '')

  const levelY = y + sc(92)
  ctx.textAlign = 'center'
  ctx.fillStyle = levelColor
  ctx.font = `700 ${sc(32)}px ${FONT}`
  ctx.fillText(data.levelLabel || data.displayLevel || level.label, x + w / 2, levelY)

  if (positionDesc) {
    ctx.fillStyle = COLORS.muted
    ctx.font = `400 ${sc(24)}px ${FONT}`
    ctx.fillText(wrapText(ctx, positionDesc, w - sc(80))[0] || positionDesc, x + w / 2, levelY + sc(34))
  }

  // 龙空龙状态灯（竖排四格，对齐首页 CSS）
  const lightsAreaY = y + sc(148)
  const lightsAreaH = sc(88)
  const lightsLx = x + sc(28)
  const lightsLw = w - sc(56)
  const cellPad = sc(8)
  const cellGap = sc(7)
  const cellW = (lightsLw - cellPad * 2 - cellGap * 3) / 4
  const cellH = sc(70)
  const cellY = lightsAreaY + cellPad
  // 「空」状态固定用琥珀警告色（与首页 risk-warning/caution 覆盖逻辑一致）
  const lightPalette = lk.state === 'empty'
    ? { bg: 'rgba(251,191,36,0.10)', border: 'rgba(251,191,36,0.55)', dot: '#fbbf24' }
    : (LEVEL_LIGHT[data.levelClass] || LEVEL_LIGHT.neutral)

  // 容器背景
  roundRect(ctx, lightsLx, lightsAreaY, lightsLw, lightsAreaH, sc(18))
  ctx.fillStyle = 'rgba(0,0,0,0.22)'
  ctx.fill()
  ctx.strokeStyle = 'rgba(255,255,255,0.04)'
  ctx.lineWidth = 1
  roundRect(ctx, lightsLx + 0.5, lightsAreaY + 0.5, lightsLw - 1, lightsAreaH - 1, sc(18))
  ctx.stroke()

  LONGKONG_STATE_STEPS.forEach((step, i) => {
    const active = step.state === lk.state
    const cx = lightsLx + cellPad + i * (cellW + cellGap)
    const centerX = cx + cellW / 2

    // 单格背景
    roundRect(ctx, cx, cellY, cellW, cellH, sc(12))
    ctx.fillStyle = active ? lightPalette.bg : 'transparent'
    ctx.fill()
    if (active) {
      ctx.strokeStyle = lightPalette.border
      ctx.lineWidth = 1.5
      roundRect(ctx, cx + 0.5, cellY + 0.5, cellW - 1, cellH - 1, sc(12))
      ctx.stroke()
    }

    // 圆点（激活时加光晕）
    const dotR = sc(6)
    const dotY = cellY + sc(22)
    ctx.beginPath()
    ctx.arc(centerX, dotY, dotR, 0, Math.PI * 2)
    if (active) {
      ctx.shadowColor = lightPalette.dot
      ctx.shadowBlur = sc(12)
    }
    ctx.fillStyle = active ? lightPalette.dot : 'rgba(255,255,255,0.22)'
    ctx.fill()
    ctx.shadowBlur = 0

    // 标签
    ctx.font = `${active ? 700 : 400} ${sc(23)}px ${FONT}`
    ctx.fillStyle = active ? lightPalette.dot : 'rgba(255,255,255,0.28)'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'alphabetic'
    ctx.fillText(step.label, centerX, dotY + dotR + sc(22))
  })

  const gx = x + sc(28)
  const gy = y + sc(248)
  const gw = w - sc(56)
  ctx.save()
  roundRect(ctx, gx, gy, gw, gaugeH, sc(14))
  const grad = ctx.createLinearGradient(gx, gy, gx, gy + gaugeH)
  grad.addColorStop(0, COLORS.gaugeWellTop)
  grad.addColorStop(1, COLORS.gaugeWellBottom)
  ctx.fillStyle = grad
  ctx.fill()
  ctx.clip()
  ctx.translate(gx, gy)
  drawSteeringGauge(ctx, gw, gaugeH, score, 'dark', { skipClear: true, bandWidth: sc(28) })
  const hubY = gaugeH * 0.58
  ctx.fillStyle = levelColor
  ctx.font = `700 ${sc(92)}px ${FONT}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(String(Math.round(score)), gw / 2, hubY)
  ctx.fillStyle = COLORS.muted
  ctx.font = `500 ${sc(24)}px ${FONT}`
  ctx.fillText('情绪分', gw / 2, hubY + sc(54))
  ctx.restore()

  let footY = gy + gaugeH + sc(20)
  if (data.scoreMode === 'live' && data.baselineScore != null) {
    ctx.fillStyle = COLORS.dim
    ctx.font = `400 ${sc(22)}px ${FONT}`
    ctx.textAlign = 'center'
    ctx.fillText(`基准分 ${data.baselineScore} · 昨日+外围，盘中不变`, x + w / 2, footY)
    footY += sc(28)
  }
  if (data.emptyWarning) {
    const tip = riskCopy?.tip || '复盘提示：综合情绪偏弱，打板少做、精选，等更强确认。'
    ctx.fillStyle = COLORS.green
    ctx.font = `400 ${sc(20)}px ${FONT}`
    const tipLines = wrapText(ctx, tip, w - sc(56)).slice(0, 2)
    // 末尾孤立标点合并到上一行
    if (tipLines.length === 2 && /^[。！？…]$/.test(tipLines[1].trim())) {
      tipLines[0] = tipLines[0] + tipLines[1].trim()
      tipLines.length = 1
    }
    tipLines.forEach((line, i) => ctx.fillText(line, x + w / 2, footY + i * sc(28)))
  }
  return h
}

function drawGridCell(ctx, cx, cy, cellW, cellH, cell, sectionId) {
  roundRect(ctx, cx, cy, cellW, cellH, sc(14))
  ctx.fillStyle = COLORS.cell
  ctx.fill()
  ctx.strokeStyle = COLORS.borderLight
  ctx.lineWidth = 1
  roundRect(ctx, cx + 0.5, cy + 0.5, cellW - 1, cellH - 1, sc(14))
  ctx.stroke()

  const val = String(cell.displayValue || cell.value || '--')
  const arrow = cell.trendArrow || ''
  ctx.font = `700 ${sc(32)}px ${FONT}`
  const valW = ctx.measureText(val).width
  const rowY = cy + sc(38)
  const startX = cx + cellW / 2 - valW / 2 - (arrow ? sc(12) : 0)
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = cellValueColor(cell.key)
  ctx.fillText(val, startX, rowY)
  if (arrow) {
    ctx.fillStyle = cell.trendGood === true ? COLORS.red : (cell.trendGood === false ? COLORS.green : COLORS.muted)
    ctx.font = `600 ${sc(24)}px ${FONT}`
    ctx.fillText(arrow, startX + valW + sc(4), rowY)
  }
  ctx.textAlign = 'center'
  ctx.fillStyle = COLORS.muted
  ctx.font = `400 ${sc(20)}px ${FONT}`
  ctx.fillText(String(cell.label || ''), cx + cellW / 2, cy + sc(72))
  const prevText = cellPrevText(cell, sectionId)
  if (prevText) {
    ctx.fillStyle = COLORS.dim
    ctx.font = `400 ${sc(18)}px ${FONT}`
    ctx.fillText(prevText, cx + cellW / 2, cy + sc(98))
  }
}

function drawPeripheralCell(ctx, cx, cy, cellW, cellH, cell) {
  roundRect(ctx, cx, cy, cellW, cellH, sc(14))
  ctx.fillStyle = COLORS.cell
  ctx.fill()
  ctx.strokeStyle = COLORS.borderLight
  ctx.lineWidth = 1
  ctx.stroke()
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = COLORS.muted
  ctx.font = `400 ${sc(18)}px ${FONT}`
  ctx.fillText(String(cell.label || ''), cx + cellW / 2, cy + sc(28))
  ctx.fillStyle = COLORS.text
  ctx.font = `700 ${sc(28)}px ${FONT}`
  ctx.fillText(String(cell.price || cell.value || '--'), cx + cellW / 2, cy + sc(62))
  if (cell.chgText) {
    ctx.fillStyle = cell.up ? COLORS.red : COLORS.green
    ctx.font = `600 ${sc(22)}px ${FONT}`
    ctx.fillText(cell.chgText, cx + cellW / 2, cy + sc(96))
  }
}

function calcSectionCardHeight(section) {
  if (section.pending) return sc(28) + sc(44) + sc(60) + sc(28)
  if (section.layout === 'row3') return sc(28) + sc(44) + sc(110) + sc(28)
  const rows = section.rows?.length || 1
  return sc(28) + sc(44) + rows * (GRID_CELL_H + GRID_GAP) - GRID_GAP + sc(28)
}

function drawSectionCard(ctx, x, y, w, section) {
  const h = calcSectionCardHeight(section)
  drawCard(ctx, x, y, w, h)
  drawSectionHead(ctx, x + sc(28), y + sc(40), w - sc(56), section.title, section.meta || '')
  const contentY = y + sc(68)

  if (section.pending) {
    ctx.textAlign = 'center'
    ctx.fillStyle = COLORS.dim
    ctx.font = `400 ${sc(24)}px ${FONT}`
    ctx.fillText('9:30 开盘后实时更新', x + w / 2, y + sc(100))
    return h
  }

  if (section.layout === 'row3') {
    const items = section.items || []
    const cellW = (w - sc(56) - GRID_GAP * 2) / 3
    items.slice(0, 3).forEach((cell, i) => {
      drawPeripheralCell(ctx, x + sc(28) + i * (cellW + GRID_GAP), contentY, cellW, sc(110), cell)
    })
    return h
  }

  const cols = section.cols || 3
  const cellW = (w - sc(56) - GRID_GAP * (cols - 1)) / cols
  ;(section.rows || []).forEach((row, rowIdx) => {
    row.forEach((cell, colIdx) => {
      if (!cell) return
      drawGridCell(
        ctx,
        x + sc(28) + colIdx * (cellW + GRID_GAP),
        contentY + rowIdx * (GRID_CELL_H + GRID_GAP),
        cellW,
        GRID_CELL_H,
        cell,
        section.id,
      )
    })
  })
  return h
}

function calcTrendCardHeight() {
  return sc(28) + sc(44) + sc(200) + sc(28)
}

function drawTrendCard(ctx, x, y, w, trend) {
  const h = calcTrendCardHeight()
  drawCard(ctx, x, y, w, h)
  ctx.textAlign = 'left'
  ctx.fillStyle = COLORS.text
  ctx.font = `600 ${sc(28)}px ${FONT}`
  ctx.textBaseline = 'alphabetic'
  ctx.fillText('近 10 日情绪趋势', x + sc(28), y + sc(40))

  if (!trend?.length) return h

  const padL = sc(28)
  const padT = sc(16)
  const innerW = w - sc(56) - sc(40)
  const innerH = sc(160)
  const chartX = x + sc(28)
  const chartY = y + sc(72)
  const n = trend.length

  ctx.save()
  ctx.translate(chartX, chartY)
  ctx.strokeStyle = 'rgba(255,255,255,0.06)'
  for (let i = 0; i <= 4; i++) {
    const ly = padT + (innerH / 4) * i
    ctx.beginPath()
    ctx.moveTo(padL, ly)
    ctx.lineTo(padL + innerW, ly)
    ctx.stroke()
  }

  const points = trend.map((item, i) => ({
    x: padL + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW),
    y: padT + innerH - (Math.max(0, Math.min(100, item.score)) / 100) * innerH,
    date: item.date,
  }))

  ctx.strokeStyle = COLORS.red
  ctx.lineWidth = 2
  ctx.beginPath()
  points.forEach((p, i) => { if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y) })
  ctx.stroke()

  points.forEach((p, i) => {
    ctx.fillStyle = COLORS.red
    ctx.beginPath()
    ctx.arc(p.x, p.y, sc(4), 0, Math.PI * 2)
    ctx.fill()
    if (i === 0 || i === Math.floor((n - 1) / 2) || i === n - 1) {
      ctx.fillStyle = COLORS.dim
      ctx.font = `${sc(18)}px ${FONT}`
      ctx.textAlign = 'center'
      ctx.fillText(String(p.date), p.x, padT + innerH + sc(18))
    }
  })
  ctx.restore()
  return h
}

function calcFooterHeight() {
  return sc(28) + sc(40) + sc(156) + sc(48) + sc(28)
}

function drawFooter(ctx, x, y, w) {
  const qrSize = sc(140)
  const h = calcFooterHeight()
  drawCard(ctx, x, y, w, h)

  ctx.textAlign = 'center'
  ctx.textBaseline = 'alphabetic'
  ctx.fillStyle = COLORS.muted
  ctx.font = `400 ${sc(22)}px ${FONT}`
  ctx.fillText('数据仅供参考，不构成投资建议', x + w / 2, y + sc(36))

  const qrX = x + (w - qrSize) / 2
  const qrY = y + sc(52)
  drawQrCode(ctx, qrX, qrY, qrSize)

  ctx.fillStyle = COLORS.red
  ctx.font = `600 ${sc(28)}px ${FONT}`
  ctx.fillText('完整实时数据更新', x + w / 2, qrY + qrSize + sc(40))

  ctx.fillStyle = COLORS.dim
  ctx.font = `400 ${sc(20)}px ${FONT}`
  ctx.fillText('扫码访问', x + w / 2, qrY + qrSize + sc(72))

  return h
}

function drawTopBrand(ctx, x, y, w, data) {
  const h = drawTopBrandHeight()
  ctx.textBaseline = 'alphabetic'

  ctx.textAlign = 'left'
  ctx.fillStyle = COLORS.red
  ctx.font = `700 ${sc(36)}px ${FONT}`
  ctx.fillText('明日当空', x, y + sc(38))

  ctx.textAlign = 'right'
  ctx.fillStyle = COLORS.muted
  ctx.font = `400 ${sc(24)}px ${FONT}`
  ctx.fillText(formatHeaderDate(), x + w, y + sc(38))

  const ref = data.refDate || data.adviceDate || ''
  ctx.textAlign = 'center'
  ctx.fillStyle = COLORS.dim
  ctx.font = `400 ${sc(22)}px ${FONT}`
  ctx.fillText(ref ? `参考日 ${ref}` : 'A股短线情绪 · 日更', x + w / 2, y + sc(82))

  return h
}

export function calcPosterHeight(data) {
  const sections = getPosterSections(data)
  let h = PAD + drawTopBrandHeight() + CARD_GAP
  h += calcQuoteCardHeight(2) + CARD_GAP
  h += calcGaugeCardHeight(data) + CARD_GAP
  sections.forEach((sec) => { h += calcSectionCardHeight(sec) + CARD_GAP })
  h += calcFooterHeight() + PAD
  return Math.max(sc(960), Math.ceil(h))
}

function drawTopBrandHeight() {
  return sc(96)
}

/**
 * @param {CanvasRenderingContext2D} ctx
 * @param {object} data API /api/sentiment/today 的 data
 */
export function drawDouyinPoster(ctx, data) {
  const w = POSTER_W
  const h = calcPosterHeight(data)
  // 勿 resetTransform：外层已按 dpr 缩放，reset 会导致导出 PNG 只占左上角 1/4
  ctx.clearRect(0, 0, w, h)
  drawPageBackground(ctx, w, h)

  const quote = formatQuote()
  const sections = getPosterSections(data)
  let y = PAD

  y += drawTopBrand(ctx, PAD, y, INNER_W, data) + CARD_GAP
  y += drawQuoteCard(ctx, PAD, y, INNER_W, quote) + CARD_GAP
  y += drawGaugeCard(ctx, PAD, y, INNER_W, data) + CARD_GAP
  sections.forEach((sec) => {
    y += drawSectionCard(ctx, PAD, y, INNER_W, sec) + CARD_GAP
  })
  drawFooter(ctx, PAD, y, INNER_W)

  return { width: w, height: h }
}

function syncCanvasDisplaySize(canvas, logicalW, logicalH) {
  const wrap = canvas.parentElement
  const wrapW = wrap?.clientWidth || logicalW
  const cssH = Math.max(240, Math.round((logicalH / logicalW) * wrapW))
  canvas.style.width = '100%'
  canvas.style.height = `${cssH}px`
  if (wrap) wrap.style.minHeight = `${cssH}px`
}

export function renderPosterToCanvas(data, canvas) {
  if (!canvas) throw new Error('canvas 不存在')
  const height = calcPosterHeight(data)
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvas.width = POSTER_W * dpr
  canvas.height = height * dpr
  syncCanvasDisplaySize(canvas, POSTER_W, height)
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('无法创建 Canvas 上下文')
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.scale(dpr, dpr)
  return drawDouyinPoster(ctx, data)
}

export function posterFilename(data) {
  const displayScore = data.displayScore != null ? data.displayScore : data.score
  const d = data.adviceDate || data.date || ''
  const day = /^\d{8}$/.test(String(d)) ? String(d) : new Date().toISOString().slice(0, 10).replace(/-/g, '')
  return `明日当空-情绪${Math.round(Number(displayScore) || 0)}-${day}.jpg`
}

export async function posterToBlob(data) {
  const canvas = document.createElement('canvas')
  renderPosterToCanvas(data, canvas)
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob)
      else reject(new Error('生成图片失败'))
    }, 'image/jpeg', 0.92)
  })
}

export const POSTER_H = sc(1200)
