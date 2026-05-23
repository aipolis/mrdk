import qrcode from './qrcode.js'

export const SITE_QR_URL = 'https://mrdk.pages.dev/'

/**
 * 在 Canvas 上绘制网址二维码（白底黑块）
 */
export function drawQrCode(ctx, x, y, size, text = SITE_QR_URL) {
  const qr = qrcode(0, 'M')
  qr.addData(text)
  qr.make()
  const n = qr.getModuleCount()
  const pad = Math.max(4, Math.round(size * 0.04))
  const inner = size - pad * 2
  const cell = inner / n

  roundRect(ctx, x, y, size, size, Math.round(size * 0.08))
  ctx.fillStyle = '#ffffff'
  ctx.fill()
  ctx.strokeStyle = 'rgba(255,255,255,0.12)'
  ctx.lineWidth = 1
  ctx.stroke()

  ctx.fillStyle = '#111111'
  for (let row = 0; row < n; row++) {
    for (let col = 0; col < n; col++) {
      if (qr.isDark(row, col)) {
        ctx.fillRect(x + pad + col * cell, y + pad + row * cell, cell, cell)
      }
    }
  }
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
