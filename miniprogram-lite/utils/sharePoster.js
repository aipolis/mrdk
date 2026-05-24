/**
 * Lite 分享海报：天气结论 + 与君共勉
 */
const { getPixelRatio } = require('./device')

const W = 750
const PAD = 40
const FONT = 'PingFang SC, sans-serif'

const THEMES = {
  long: { bg: '#1a2e1a', accent: '#52c41a', glow: 'rgba(82,196,26,0.15)' },
  mid: { bg: '#2a2618', accent: '#faad14', glow: 'rgba(250,173,20,0.12)' },
  empty: { bg: '#152030', accent: '#1890ff', glow: 'rgba(24,144,255,0.12)' },
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

function createCanvas(h) {
  const dpr = getPixelRatio()
  const canvas = wx.createOffscreenCanvas({ type: '2d', width: W * dpr, height: h * dpr })
  const ctx = canvas.getContext('2d')
  ctx.scale(dpr, dpr)
  return { canvas, ctx, dpr, h }
}

function exportPoster(canvas) {
  return new Promise((resolve, reject) => {
    wx.canvasToTempFilePath({
      canvas,
      fileType: 'png',
      quality: 1,
      success: res => (res.tempFilePath ? resolve(res.tempFilePath) : reject(new Error('empty'))),
      fail: reject,
    })
  })
}

function generateSharePoster(data) {
  const verdict = data.verdict || {}
  const theme = THEMES[verdict.key] || THEMES.mid
  const quote = data.quote || '买在分歧，卖在一致。'
  const h = 920
  const { canvas, ctx } = createCanvas(h)

  const bg = ctx.createLinearGradient(0, 0, 0, h)
  bg.addColorStop(0, '#0c1224')
  bg.addColorStop(1, theme.bg)
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, W, h)

  ctx.fillStyle = theme.glow
  ctx.fillRect(0, 0, W, h * 0.45)

  ctx.textAlign = 'left'
  ctx.fillStyle = '#ff4d4f'
  ctx.font = `700 36px ${FONT}`
  ctx.fillText('明日当空', PAD, 72)

  ctx.textAlign = 'right'
  ctx.fillStyle = '#9ca3af'
  ctx.font = `400 24px ${FONT}`
  ctx.fillText(data.headerDate || '', W - PAD, 72)

  ctx.textAlign = 'center'
  ctx.fillStyle = '#6b7280'
  ctx.font = `400 22px ${FONT}`
  ctx.fillText('识别下雨天，下雨天少出门', W / 2, 118)

  roundRect(ctx, PAD, 150, W - PAD * 2, 520, 24)
  ctx.fillStyle = 'rgba(20,26,46,0.92)'
  ctx.fill()
  ctx.strokeStyle = 'rgba(255,255,255,0.08)'
  ctx.lineWidth = 1
  ctx.stroke()

  ctx.font = `400 80px ${FONT}`
  ctx.fillText(verdict.emoji || '⛅', W / 2, 280)

  ctx.fillStyle = theme.accent
  ctx.font = `700 120px ${FONT}`
  ctx.fillText(verdict.char || '中', W / 2, 420)

  ctx.fillStyle = '#f3f4f6'
  ctx.font = `600 40px ${FONT}`
  ctx.fillText(`${verdict.weather || '多云'} · ${verdict.action || '带伞'}`, W / 2, 490)

  if (data.updatedAt) {
    ctx.fillStyle = '#6b7280'
    ctx.font = `400 22px ${FONT}`
    ctx.fillText(data.updatedAt, W / 2, 540)
  }

  roundRect(ctx, PAD + 20, 580, W - PAD * 2 - 40, 120, 16)
  ctx.fillStyle = 'rgba(255,77,79,0.12)'
  ctx.fill()
  ctx.fillStyle = '#ff4d4f'
  ctx.font = `600 22px ${FONT}`
  ctx.fillText('与君共勉', PAD + 48, 620)
  ctx.fillStyle = '#e5e7eb'
  ctx.font = `500 30px ${FONT}`
  ctx.fillText(quote, W / 2, 670, W - PAD * 2 - 80)

  ctx.fillStyle = '#6b7280'
  ctx.font = `400 20px ${FONT}`
  ctx.fillText('个人生活节律参考 · 仅供参考', W / 2, h - 48)

  return exportPoster(canvas)
}

module.exports = { generateSharePoster }
