/**
 * 情绪分仪表盘加载动画：idle 指针摆动 → settle 缓动落定
 */
const { drawSteeringGauge } = require('./gaugeDraw')

const SKIP_ANIM_MS = 300
const SETTLE_MS = 520
/** 缓存秒开时，指针至少摆动时长（ms） */
const CACHE_IDLE_MS = 2200
const IDLE_CENTER = 50
const IDLE_AMPLITUDE = 14
const SETTLE_DATA_INTERVAL_MS = 80

function easeOutCubic(t) {
  return 1 - Math.pow(1 - t, 3)
}

function clampScore(score) {
  const n = Number(score)
  if (Number.isNaN(n)) return 0
  return Math.max(0, Math.min(100, n))
}

function createGaugeController(page) {
  return {
    canvas: null,
    ctx: null,
    w: 0,
    h: 0,
    mode: 'done',
    animScore: IDLE_CENTER,
    settleFrom: IDLE_CENTER,
    targetScore: 0,
    settleStart: 0,
    idleStart: 0,
    rafToken: null,
    onSettleDone: null,
    lastDisplayUpdate: 0,

    bindCanvas(canvas, ctx, w, h) {
      this.canvas = canvas
      this.ctx = ctx
      this.w = w
      this.h = h
    },

    idleScore(now) {
      const t = (now - this.idleStart) / 1000
      const primary = Math.sin(t * 2.2)
      const secondary = 0.35 * Math.sin(t * 4.6 + 0.8)
      return IDLE_CENTER + IDLE_AMPLITUDE * (primary + secondary)
    },

    drawAt(score) {
      if (!this.ctx) return
      const theme = (page.data && page.data.uiTheme) || 'dark'
      drawSteeringGauge(this.ctx, this.w, this.h, clampScore(score), theme)
    },

    tick() {
      const now = Date.now()
      if (this.mode === 'idle') {
        this.animScore = this.idleScore(now)
        this.drawAt(this.animScore)
      } else if (this.mode === 'settle') {
        const t = Math.min(1, (now - this.settleStart) / SETTLE_MS)
        this.animScore = this.settleFrom + (this.targetScore - this.settleFrom) * easeOutCubic(t)
        this.drawAt(this.animScore)
        if (now - this.lastDisplayUpdate >= SETTLE_DATA_INTERVAL_MS) {
          this.lastDisplayUpdate = now
          page.setData({
            scoreRevealing: true,
            displayScore: String(Math.round(this.animScore))
          })
        }
        if (t >= 1) {
          this.mode = 'done'
          this.animScore = this.targetScore
          this.drawAt(this.targetScore)
          const done = this.onSettleDone
          this.onSettleDone = null
          if (done) done()
          return
        }
      } else {
        return
      }
      this.scheduleFrame()
    },

    scheduleFrame() {
      const loop = () => {
        this.rafToken = null
        this.tick()
      }
      if (this.canvas && this.canvas.requestAnimationFrame) {
        this.rafToken = this.canvas.requestAnimationFrame(loop)
      } else {
        this.rafToken = setTimeout(loop, 16)
      }
    },

    cancelFrame() {
      if (this.rafToken == null) return
      if (this.canvas && this.canvas.cancelAnimationFrame) {
        this.canvas.cancelAnimationFrame(this.rafToken)
      } else {
        clearTimeout(this.rafToken)
      }
      this.rafToken = null
    },

    startIdle() {
      this.cancelFrame()
      this.mode = 'idle'
      this.idleStart = Date.now()
      this.animScore = IDLE_CENTER
      this.drawAt(IDLE_CENTER)
      this.scheduleFrame()
    },

    settleTo(target, onDone) {
      this.cancelFrame()
      this.mode = 'settle'
      this.settleFrom = clampScore(this.animScore)
      this.targetScore = clampScore(target)
      this.settleStart = Date.now()
      this.lastDisplayUpdate = 0
      this.onSettleDone = onDone
      this.scheduleFrame()
    },

    stop() {
      this.cancelFrame()
      this.mode = 'done'
      this.onSettleDone = null
    },

    drawFinal(score) {
      this.stop()
      this.animScore = clampScore(score)
      this.targetScore = this.animScore
      this.drawAt(this.animScore)
    }
  }
}

module.exports = { createGaugeController, SKIP_ANIM_MS, CACHE_IDLE_MS }
