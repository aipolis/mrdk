/**
 * 分享海报：手机竖屏适配（格言 + 表盘 + 昨日/盘中 + 页脚）
 */
import { drawSteeringGauge } from './gaugeDraw.js?v=20260531a'
import { getDisplayLevel, formatHeaderDate, HOME_QUOTE } from './theme.js?v=20260609c'
import { scoreToLongkongState, LONGKONG_STATE_STEPS, buildRiskCopy, normalizeRiskReason, resolvePositionDisplay } from './longkongState.js?v=20260617m'
import { normalizeSections } from './indicators.js?v=20260609b'
import { drawQrCode } from './qrDraw.js?v=20260531a'
import { beijingDateKey } from './time.js?v=20260609a'

export const POSTER_W = 1080
// 抖音/视频号标准 9:16 高度。短图模式定死 1920,长图模式(预留)走动态。
export const POSTER_H_COMPACT = 1920
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
  return normalizeSections(data.indicatorSections || data.sections || [], data)
}

/** 海报仅保留昨日概览（不含外围、竞价、盘中实时、趋势图） */
function getPosterSections(data) {
  const keep = new Set(['yesterday'])
  return getSections(data).filter((sec) => keep.has(sec.id))
}

function formatQuote() {
  return /[。！？；…]$/.test(HOME_QUOTE) ? HOME_QUOTE : `${HOME_QUOTE}。`
}

function cellValueColor(cell) {
  if (cell?.valueClass === 'value-hot' || cell?.trendGood === true) return COLORS.red
  if (cell?.valueClass === 'value-cold' || cell?.trendGood === false) return COLORS.green
  return COLORS.textSoft
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
  // sc(100) → sc(160): 龙空灯区高度 +sc(50)
  // sc(292) → sc(372): 表盘高度 +sc(80)
  let h = sc(28) + sc(44) + sc(40) + sc(44) + sc(160) + sc(372) + sc(28)
  if (data.scoreMode === 'live' && data.baselineScore != null) h += sc(28)
  if (data.emptyWarning) h += sc(44)
  h += sc(60) // 今日应对 一行
  h += sc(50) // 短线接力仓位建议 一行
  return h
}

function drawGaugeCard(ctx, x, y, w, data) {
  const score = Number(data.displayScore != null ? data.displayScore : (data.score || 0))
  const level = getDisplayLevel(score)
  const levelColor = LEVEL_COLORS[data.levelClass] || level.color
  const gaugeH = sc(372) // 表盘高度,与 calcGaugeCardHeight 保持一致
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

  // 短线接力仓位建议（首页核心数字，海报必带）
  const positionDisplay = resolvePositionDisplay(data)
  const positionPercent = Number.isFinite(Number(positionDisplay.percent))
    ? Math.round(Number(positionDisplay.percent))
    : null
  if (positionPercent != null) {
    const lineY = levelY + sc(82)
    ctx.textBaseline = 'alphabetic'
    ctx.font = `400 ${sc(22)}px ${FONT}`
    const labelTxt = '短线接力仓位建议  '
    const labelW = ctx.measureText(labelTxt).width
    ctx.font = `700 ${sc(34)}px ${FONT}`
    const valTxt = `${positionPercent}%`
    const valW = ctx.measureText(valTxt).width
    const startX = x + w / 2 - (labelW + valW) / 2

    ctx.font = `400 ${sc(22)}px ${FONT}`
    ctx.fillStyle = COLORS.dim
    ctx.textAlign = 'left'
    ctx.fillText(labelTxt, startX, lineY)

    ctx.font = `700 ${sc(34)}px ${FONT}`
    ctx.fillStyle = positionPercent === 0 ? '#ef4444' : '#fbbf24'
    ctx.fillText(valTxt, startX + labelW, lineY)
  }

  // 龙空龙状态灯（竖排四格，对齐首页 CSS）—— 放大,更醒目
  const lightsAreaY = y + sc(198)
  const lightsAreaH = sc(138)
  const lightsLx = x + sc(28)
  const lightsLw = w - sc(56)
  const cellPad = sc(10)
  const cellGap = sc(8)
  const cellW = (lightsLw - cellPad * 2 - cellGap * 3) / 4
  const cellH = sc(108)
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

    // 圆点（激活时加光晕）—— 放大
    const dotR = sc(9)
    const dotY = cellY + sc(36)
    ctx.beginPath()
    ctx.arc(centerX, dotY, dotR, 0, Math.PI * 2)
    if (active) {
      ctx.shadowColor = lightPalette.dot
      ctx.shadowBlur = sc(16)
    }
    ctx.fillStyle = active ? lightPalette.dot : 'rgba(255,255,255,0.22)'
    ctx.fill()
    ctx.shadowBlur = 0

    // 标签 —— 字号加大,激活态加粗更重
    ctx.font = `${active ? 700 : 500} ${sc(30)}px ${FONT}`
    ctx.fillStyle = active ? lightPalette.dot : 'rgba(255,255,255,0.32)'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'alphabetic'
    ctx.fillText(step.label, centerX, dotY + dotR + sc(34))
  })

  const gx = x + sc(28)
  const gy = y + sc(348) // 下移以让出更大的龙空灯区域(原 sc(298),+sc(50))
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
  const scoreStr = String(Math.round(score))
  ctx.fillStyle = levelColor
  ctx.font = `700 ${sc(92)}px ${FONT}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(scoreStr, gw / 2, hubY)

  ctx.fillStyle = COLORS.muted
  ctx.font = `500 ${sc(24)}px ${FONT}`
  ctx.fillText('情绪分', gw / 2, hubY + sc(54))

  // 环比变化：放在「情绪分」下方（固定坐标，无 measureText 风险）
  const prevScore = Number(data.prevScore ?? data.previousScore)
  if (Number.isFinite(prevScore)) {
    const diff = Math.round(score) - Math.round(prevScore)
    const arrow = diff > 0 ? '↑' : diff < 0 ? '↓' : '·'
    const diffStr = diff === 0
      ? '与昨日持平'
      : `比昨日 ${arrow}${Math.abs(diff)}`
    const diffColor = diff > 0 ? '#ef4444' : diff < 0 ? '#52c41a' : COLORS.dim
    ctx.fillStyle = diffColor
    ctx.font = `600 ${sc(22)}px ${FONT}`
    ctx.textBaseline = 'alphabetic'
    ctx.fillText(diffStr, gw / 2, hubY + sc(94))
  }
  ctx.restore()

  let footY = gy + gaugeH + sc(20)
  if (data.scoreMode === 'live' && data.baselineScore != null) {
    ctx.fillStyle = COLORS.dim
    ctx.font = `400 ${sc(22)}px ${FONT}`
    ctx.textAlign = 'center'
    ctx.fillText(`基准分 ${data.baselineScore} · 昨日收盘，盘中不变`, x + w / 2, footY)
    footY += sc(28)
  }
  if (data.emptyWarning) {
    const tip = riskCopy?.tip || '复盘｜重点：接力结构偏弱；应对：控制节奏，等待确认。'
    ctx.fillStyle = COLORS.green
    ctx.font = `400 ${sc(20)}px ${FONT}`
    ctx.textAlign = 'center'
    const tipLines = wrapText(ctx, tip, w - sc(56)).slice(0, 2)
    if (tipLines.length === 2 && /^[。！？…]$/.test(tipLines[1].trim())) {
      tipLines[0] = tipLines[0] + tipLines[1].trim()
      tipLines.length = 1
    }
    tipLines.forEach((line, i) => ctx.fillText(line, x + w / 2, footY + i * sc(28)))
    footY += tipLines.length * sc(28)
  }

  // 今日应对（始终展示）
  const actionY = footY + sc(8)
  const actionText = buildTodayAction(data)
  ctx.textAlign = 'center'
  ctx.textBaseline = 'alphabetic'
  // 「今日应对」标签 + 文本，两段不同字重
  ctx.font = `400 ${sc(22)}px ${FONT}`
  ctx.fillStyle = COLORS.dim
  const labelStr = '今日应对  '
  const labelW = ctx.measureText(labelStr).width
  ctx.font = `600 ${sc(24)}px ${FONT}`
  ctx.fillStyle = '#fbbf24'
  const actionW = ctx.measureText(actionText).width
  const totalW = labelW + actionW
  const startX = x + w / 2 - totalW / 2
  ctx.font = `400 ${sc(22)}px ${FONT}`
  ctx.fillStyle = COLORS.dim
  ctx.textAlign = 'left'
  ctx.fillText(labelStr, startX, actionY + sc(20))
  ctx.font = `600 ${sc(24)}px ${FONT}`
  ctx.fillStyle = '#fbbf24'
  ctx.fillText(actionText, startX + labelW, actionY + sc(20))

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
  const valueColor = cellValueColor(cell)
  ctx.fillStyle = valueColor
  ctx.fillText(val, startX, rowY)
  if (arrow) {
    ctx.fillStyle = valueColor
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
  // top + QR + cta + divider gap + 平台合并行 + disclaimer + bottom
  return sc(24) + sc(120) + sc(36) + sc(22) + sc(36) + sc(36) + sc(20)
}

function drawFooter(ctx, x, y, w) {
  const qrSize = sc(120)
  const h = calcFooterHeight()
  drawCard(ctx, x, y, w, h)

  // 二维码
  const qrX = x + (w - qrSize) / 2
  const qrY = y + sc(24)
  drawQrCode(ctx, qrX, qrY, qrSize)

  ctx.textAlign = 'center'
  ctx.textBaseline = 'alphabetic'

  // 主标：扫码进入实时面板
  ctx.fillStyle = COLORS.red
  ctx.font = `600 ${sc(26)}px ${FONT}`
  ctx.fillText('扫码进入实时面板', x + w / 2, qrY + qrSize + sc(36))

  // 分隔细线
  const divY = qrY + qrSize + sc(54)
  const divW = sc(100)
  ctx.strokeStyle = 'rgba(255,255,255,0.10)'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(x + w / 2 - divW / 2, divY)
  ctx.lineTo(x + w / 2 + divW / 2, divY)
  ctx.stroke()

  // 平台合并行：公众号 / 抖音 · 量化新手村
  ctx.fillStyle = COLORS.textSoft
  ctx.font = `500 ${sc(22)}px ${FONT}`
  ctx.fillText('公众号 / 抖音搜 · 量化新手村', x + w / 2, qrY + qrSize + sc(86))

  // 免责声明 —— 最底,小字
  ctx.fillStyle = COLORS.dim
  ctx.font = `400 ${sc(18)}px ${FONT}`
  ctx.fillText('数据仅供参考，不构成投资建议', x + w / 2, y + h - sc(16))

  return h
}

function drawTopBrand(ctx, x, y, w, data) {
  const h = drawTopBrandHeight()
  ctx.textBaseline = 'alphabetic'

  // 主标：明日当空（左上）
  ctx.textAlign = 'left'
  ctx.fillStyle = COLORS.red
  ctx.font = `700 ${sc(36)}px ${FONT}`
  ctx.fillText('明日当空', x, y + sc(38))

  // 母品牌挂名（左下小字）
  ctx.fillStyle = COLORS.dim
  ctx.font = `400 ${sc(20)}px ${FONT}`
  ctx.fillText('量化新手村 旗下 · A股短线情绪', x, y + sc(72))

  // 日期（右上）
  ctx.textAlign = 'right'
  ctx.fillStyle = COLORS.muted
  ctx.font = `400 ${sc(24)}px ${FONT}`
  ctx.fillText(formatHeaderDate(), x + w, y + sc(38))

  // 参考日（右下小字）
  const ref = data.refDate || data.adviceDate || ''
  if (ref) {
    ctx.fillStyle = COLORS.dim
    ctx.font = `400 ${sc(18)}px ${FONT}`
    ctx.fillText(`参考日 ${ref}`, x + w, y + sc(72))
  }

  return h
}

/** 根据当日情绪状态生成"今日应对"一句话 */
function buildTodayAction(data) {
  if (data?.emptyWarning) return '建议清仓 · 等待修复确认'
  const score = Math.round(Number(data?.displayScore ?? data?.score ?? 0))
  if (score >= 80) return '情绪高涨,警惕分歧 · 跟高分股设好止损'
  if (score >= 60) return '可关注模型高分股 · 留意盘中分歧'
  if (score >= 50) return '情绪修复中 · 仓位偏轻试错'
  if (score >= 40) return '减少接力 · 只做最强一线'
  return '空仓为主 · 等待方向选择'
}

// 紧凑(默认)模式固定 1080×1920。drawDouyinPoster 内部自适应间距。
// 长图模式高度计算保留为 calcLongPosterHeight,后续如需多档输出可直接调用。
export function calcPosterHeight() {
  return POSTER_H_COMPACT
}

export function calcLongPosterHeight(data) {
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
  const h = POSTER_H_COMPACT
  // 勿 resetTransform：外层已按 dpr 缩放，reset 会导致导出 PNG 只占左上角 1/4
  ctx.clearRect(0, 0, w, h)
  drawPageBackground(ctx, w, h)

  // 三块核心(舍弃 quote 和 yesterday sections,因为 9:16 高度装不下且这些是次要信息):
  //   1. 顶部品牌 + 日期
  //   2. 情绪表盘(已含:情绪分大数字 / 等级 / 龙空灯 / 今日应对 / 仓位建议)
  //   3. 底部 CTA(二维码 + 公众号 + 抖音引导)
  const brandH = drawTopBrandHeight()
  const gaugeH = calcGaugeCardHeight(data)
  const footerH = calcFooterHeight()

  // 剩余空间均分到两个 gap 上;cap 在 sc(50) 内,避免中间出现明显"留空感"
  // 极端情况(usable < 0,emptyWarning + live 双触发)允许 gap=0,卡片相邻不重叠
  const usable = h - PAD * 2 - brandH - gaugeH - footerH
  const gap = usable > CARD_GAP * 2
    ? Math.min(sc(50), Math.floor(usable / 2))
    : Math.max(0, Math.floor(usable / 2))

  let y = PAD
  y += drawTopBrand(ctx, PAD, y, INNER_W, data) + gap
  y += drawGaugeCard(ctx, PAD, y, INNER_W, data) + gap
  drawFooter(ctx, PAD, y, INNER_W)

  return { width: w, height: h }
}

// ============================================================
//  龙空预警海报 (Alert Mode) —— 强情绪信号专属海报，传播力 5-10x
// ============================================================

const ALERT_RED = '#dc2626'
const ALERT_RED_SOFT = '#fca5a5'
const ALERT_AMBER = '#fbbf24'

export function isAlertModeAvailable(data) {
  if (!data) return false
  if (data.emptyWarning) return true
  if (data.riskLevel === 'warning' || data.riskLevel === 'critical') return true
  const score = Number(data.displayScore ?? data.score ?? 50)
  return Number.isFinite(score) && score < 35
}

function drawAlertTopBrand(ctx, x, y, w) {
  ctx.textBaseline = 'alphabetic'

  ctx.textAlign = 'left'
  ctx.fillStyle = ALERT_RED
  ctx.font = `700 ${sc(42)}px ${FONT}`
  ctx.fillText('明日当空', x, y + sc(44))

  ctx.textAlign = 'right'
  ctx.fillStyle = COLORS.muted
  ctx.font = `400 ${sc(24)}px ${FONT}`
  ctx.fillText(formatHeaderDate(), x + w, y + sc(44))

  ctx.textAlign = 'center'
  ctx.fillStyle = COLORS.dim
  ctx.font = `400 ${sc(22)}px ${FONT}`
  ctx.fillText('龙空预警 · 短线避险参考', x + w / 2, y + sc(82))

  return sc(96)
}

function drawAlertWarningCard(ctx, x, y, w, data) {
  const h = sc(380) // sc(540) → sc(380),压缩 sc(160) 内部 padding

  // 红色调渐变背景 + 红色边框
  roundRect(ctx, x, y, w, h, sc(20))
  const bg = ctx.createLinearGradient(0, y, 0, y + h)
  bg.addColorStop(0, 'rgba(220, 38, 38, 0.18)')
  bg.addColorStop(1, 'rgba(220, 38, 38, 0.04)')
  ctx.fillStyle = bg
  ctx.fill()
  ctx.strokeStyle = 'rgba(220, 38, 38, 0.55)'
  ctx.lineWidth = sc(2)
  roundRect(ctx, x + 1, y + 1, w - 2, h - 2, sc(20))
  ctx.stroke()

  // ⚠ + 主标题 同一行,左右对齐(原来上下两行各占 ~sc(70),合并节省空间)
  ctx.fillStyle = ALERT_AMBER
  ctx.font = `700 ${sc(54)}px ${FONT}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'alphabetic'
  // 用 measure 计算总宽度,使图标和文字水平居中
  const iconStr = '⚠ '
  const titleStr = '龙空信号触发'
  const iconW = ctx.measureText(iconStr).width
  ctx.font = `700 ${sc(42)}px ${FONT}`
  const titleW = ctx.measureText(titleStr).width
  const totalW = iconW + titleW
  const lineY = y + sc(72)
  const startX = x + w / 2 - totalW / 2
  ctx.font = `700 ${sc(54)}px ${FONT}`
  ctx.fillStyle = ALERT_AMBER
  ctx.textAlign = 'left'
  ctx.fillText(iconStr, startX, lineY)
  ctx.font = `700 ${sc(42)}px ${FONT}`
  ctx.fillStyle = ALERT_RED_SOFT
  ctx.fillText(titleStr, startX + iconW, lineY - sc(4))

  // 巨型情绪分
  const score = Math.round(Number(data?.displayScore ?? data?.score ?? 0))
  ctx.textAlign = 'center'
  ctx.fillStyle = '#ef4444'
  ctx.font = `800 ${sc(150)}px ${FONT}`
  ctx.textBaseline = 'middle'
  ctx.fillText(String(score), x + w / 2, y + sc(210))

  ctx.fillStyle = COLORS.muted
  ctx.font = `500 ${sc(22)}px ${FONT}`
  ctx.textBaseline = 'alphabetic'
  ctx.fillText('情绪分', x + w / 2, y + sc(300))

  // 状态描述
  const riskCopy = buildRiskCopy(data)
  const desc = riskCopy?.desc || data?.positionDesc || '接力结构偏弱，风险优先'
  const cleanDesc = String(desc).replace(/。$/, '')
  ctx.fillStyle = COLORS.textSoft
  ctx.font = `500 ${sc(26)}px ${FONT}`
  ctx.fillText(cleanDesc, x + w / 2, y + sc(346))

  return h
}

function pickAlertReasons(data) {
  const raw = (data?.emptyReasons || data?.positionReasons || [])
    .map(normalizeRiskReason)
    .filter(Boolean)
  const concrete = raw.filter((r) => /晋级率|炸板率|跌停|连板|溢价|封板率|情绪分/.test(r))
  return [...new Set([...concrete, ...raw])].slice(0, 4)
}

function calcAlertReasonsHeight(reasons) {
  const lineH = sc(42) // sc(48) → sc(42),行距压缩
  const count = Math.max(1, reasons.length)
  return sc(40) + sc(36) + count * lineH + sc(16)
}

function drawAlertReasonsCard(ctx, x, y, w, data) {
  const reasons = pickAlertReasons(data)
  const h = calcAlertReasonsHeight(reasons)
  drawCard(ctx, x, y, w, h)

  ctx.textAlign = 'left'
  ctx.textBaseline = 'alphabetic'
  ctx.fillStyle = COLORS.text
  ctx.font = `600 ${sc(28)}px ${FONT}`
  ctx.fillText('风险点', x + sc(28), y + sc(40))

  if (reasons.length === 0) {
    ctx.fillStyle = COLORS.muted
    ctx.font = `400 ${sc(22)}px ${FONT}`
    ctx.fillText('— 接力结构整体偏弱 —', x + sc(28), y + sc(40) + sc(42))
  } else {
    const lineH = sc(42)
    reasons.forEach((reason, i) => {
      const ly = y + sc(40) + sc(42) + i * lineH
      ctx.fillStyle = '#ef4444'
      ctx.beginPath()
      ctx.arc(x + sc(42), ly - sc(8), sc(5), 0, Math.PI * 2)
      ctx.fill()

      ctx.fillStyle = COLORS.textSoft
      ctx.font = `500 ${sc(24)}px ${FONT}`
      ctx.textAlign = 'left'
      const maxW = w - sc(70) - sc(28)
      const line = wrapText(ctx, reason, maxW)[0] || reason
      ctx.fillText(line, x + sc(64), ly)
    })
  }
  return h
}

function drawAlertPositionCard(ctx, x, y, w, data) {
  const h = sc(200) // sc(280) → sc(200),压缩 sc(80)
  drawCard(ctx, x, y, w, h)

  ctx.textAlign = 'left'
  ctx.textBaseline = 'alphabetic'
  ctx.fillStyle = COLORS.muted
  ctx.font = `500 ${sc(22)}px ${FONT}`
  ctx.fillText('短线接力仓位建议', x + sc(28), y + sc(36))

  const positionPercent = data?.emptyWarning ? 0 : Number(data?.positionPercent ?? 0)
  const isZero = positionPercent === 0
  ctx.fillStyle = isZero ? '#ef4444' : ALERT_AMBER
  ctx.font = `800 ${sc(96)}px ${FONT}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(`${positionPercent}%`, x + w / 2, y + sc(112))

  ctx.fillStyle = COLORS.textSoft
  ctx.font = `500 ${sc(22)}px ${FONT}`
  ctx.textBaseline = 'alphabetic'
  const tip = isZero ? '建议清仓 / 减仓 · 等待修复' : '控制节奏 · 等待信号确认'
  ctx.fillText(tip, x + w / 2, y + sc(176))

  return h
}

export function calcAlertPosterHeight(data) {
  const reasons = pickAlertReasons(data)
  let h = PAD
  h += sc(96) + CARD_GAP
  h += sc(380) + CARD_GAP // 警示卡压缩 sc(540)→sc(380)
  h += calcAlertReasonsHeight(reasons) + CARD_GAP
  h += sc(200) + CARD_GAP // 仓位卡压缩 sc(280)→sc(200)
  h += calcFooterHeight() + PAD // 与完整版页脚保持一致
  return Math.ceil(h)
}

export function drawAlertPoster(ctx, data) {
  const w = POSTER_W
  const h = calcAlertPosterHeight(data)
  ctx.clearRect(0, 0, w, h)
  drawPageBackground(ctx, w, h)

  let y = PAD
  y += drawAlertTopBrand(ctx, PAD, y, INNER_W) + CARD_GAP
  y += drawAlertWarningCard(ctx, PAD, y, INNER_W, data) + CARD_GAP
  y += drawAlertReasonsCard(ctx, PAD, y, INNER_W, data) + CARD_GAP
  y += drawAlertPositionCard(ctx, PAD, y, INNER_W, data) + CARD_GAP
  drawFooter(ctx, PAD, y, INNER_W) // 与完整版统一,弃用 drawAlertFooter

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

function resolvePosterMode(data, requested) {
  if (requested === 'alert' || requested === 'full') return requested
  return isAlertModeAvailable(data) ? 'alert' : 'full'
}

export function renderPosterToCanvas(data, canvas, options = {}) {
  if (!canvas) throw new Error('canvas 不存在')
  const mode = resolvePosterMode(data, options.mode)
  const height = mode === 'alert' ? calcAlertPosterHeight(data) : calcPosterHeight(data)
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvas.width = POSTER_W * dpr
  canvas.height = height * dpr
  syncCanvasDisplaySize(canvas, POSTER_W, height)
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('无法创建 Canvas 上下文')
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.scale(dpr, dpr)
  return mode === 'alert' ? drawAlertPoster(ctx, data) : drawDouyinPoster(ctx, data)
}

export function posterFilename(data, mode = 'full') {
  const displayScore = data.displayScore != null ? data.displayScore : data.score
  const d = data.adviceDate || data.date || ''
  const day = /^\d{8}$/.test(String(d)) ? String(d) : beijingDateKey()
  const prefix = mode === 'alert' ? '明日当空-龙空预警' : '明日当空-情绪'
  return `${prefix}${Math.round(Number(displayScore) || 0)}-${day}.jpg`
}

export async function posterToBlob(data, options = {}) {
  const canvas = document.createElement('canvas')
  renderPosterToCanvas(data, canvas, options)
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob)
      else reject(new Error('生成图片失败'))
    }, 'image/jpeg', 0.92)
  })
}

export const POSTER_H = sc(1200)
