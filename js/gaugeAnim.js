import { drawSteeringGauge } from './gaugeDraw.js?v=20260527d'

export const SKIP_ANIM_MS = 300
/** 指针摆动总时长（含渐大→渐小） */
export const IDLE_MIN_MS = 2600
export const SETTLE_MS = 1100

const IDLE_CENTER = 50
const IDLE_AMP_MIN = 5
const IDLE_AMP_MAX = 32
const SETTLE_DATA_INTERVAL_MS = 50

function smoothstep(u) {
  const t = Math.max(0, Math.min(1, u))
  return t * t * (3 - 2 * t)
}

/** 摆幅包络：小 → 大 → 小，落定前收住 */
function idleAmplitudeEnvelope(progress) {
  const p = Math.max(0, Math.min(1, progress))
  if (p < 0.4) {
    const u = smoothstep(p / 0.4)
    return IDLE_AMP_MIN + (IDLE_AMP_MAX - IDLE_AMP_MIN) * u
  }
  if (p < 0.55) {
    return IDLE_AMP_MAX
  }
  const u = smoothstep((p - 0.55) / 0.45)
  return IDLE_AMP_MAX - (IDLE_AMP_MAX - IDLE_AMP_MIN * 0.6) * u
}

function easeOutQuart(t) {
  return 1 - Math.pow(1 - t, 4)
}

function clampScore(score) {
  const n = Number(score)
  if (Number.isNaN(n)) return 0
  return Math.max(0, Math.min(100, n))
}

export function createGaugeController(options = {}) {
  const getTheme = options.getTheme || (() => 'dark')
  const onScoreReveal = options.onScoreReveal || (() => {})

  let canvas = null
  let ctx = null
  let w = 0
  let h = 0
  let mode = 'done'
  let animScore = IDLE_CENTER
  let settleFrom = IDLE_CENTER
  let targetScore = 0
  let settleStart = 0
  let idleStart = 0
  let idleDurationMs = IDLE_MIN_MS
  let rafToken = null
  let onSettleDone = null
  let lastDisplayUpdate = 0

  function bindCanvas(el) {
    canvas = el || canvas
    if (!canvas) return false
    const dpr = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    if (!rect.width || !rect.height) return false
    w = rect.width
    h = rect.height
    canvas.width = Math.round(w * dpr)
    canvas.height = Math.round(h * dpr)
    ctx = canvas.getContext('2d')
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    return true
  }

  function idleScore(now) {
    const elapsed = now - idleStart
    const progress = Math.min(1, elapsed / idleDurationMs)
    const amp = idleAmplitudeEnvelope(progress)
    const t = elapsed / 1000
    const primary = Math.sin(t * 1.42)
    const secondary = 0.4 * Math.sin(t * 2.75 + 0.55)
    const tertiary = 0.15 * Math.sin(t * 4.6 + 1.1)
    const wave = primary + secondary + tertiary
    return IDLE_CENTER + amp * wave
  }

  function drawAt(score) {
    if (!ctx) return
    drawSteeringGauge(ctx, w, h, clampScore(score), getTheme())
  }

  function tick() {
    const now = Date.now()
    if (mode === 'idle') {
      animScore = idleScore(now)
      drawAt(animScore)
    } else if (mode === 'settle') {
      const t = Math.min(1, (now - settleStart) / SETTLE_MS)
      animScore = settleFrom + (targetScore - settleFrom) * easeOutQuart(t)
      drawAt(animScore)
      if (now - lastDisplayUpdate >= SETTLE_DATA_INTERVAL_MS) {
        lastDisplayUpdate = now
        onScoreReveal(Math.round(clampScore(animScore)))
      }
      if (t >= 1) {
        mode = 'done'
        animScore = targetScore
        drawAt(targetScore)
        onScoreReveal(Math.round(targetScore))
        const done = onSettleDone
        onSettleDone = null
        if (done) done()
        return
      }
    } else {
      return
    }
    scheduleFrame()
  }

  function scheduleFrame() {
    const loop = () => {
      rafToken = null
      tick()
    }
    rafToken = window.requestAnimationFrame(loop)
  }

  function cancelFrame() {
    if (rafToken == null) return
    window.cancelAnimationFrame(rafToken)
    rafToken = null
  }

  return {
    bindCanvas,
    startIdle(durationMs = IDLE_MIN_MS) {
      cancelFrame()
      mode = 'idle'
      idleStart = Date.now()
      idleDurationMs = Math.max(1200, durationMs || IDLE_MIN_MS)
      animScore = IDLE_CENTER
      if (bindCanvas(canvas)) drawAt(IDLE_CENTER)
      scheduleFrame()
    },
    settleTo(target, onDone) {
      cancelFrame()
      mode = 'settle'
      settleFrom = clampScore(animScore)
      targetScore = clampScore(target)
      settleStart = Date.now()
      lastDisplayUpdate = 0
      onSettleDone = onDone
      scheduleFrame()
    },
    stop() {
      cancelFrame()
      mode = 'done'
      onSettleDone = null
    },
    drawFinal(score) {
      cancelFrame()
      mode = 'done'
      animScore = clampScore(score)
      targetScore = animScore
      if (bindCanvas(canvas)) drawAt(animScore)
    },
    isIdle() {
      return mode === 'idle'
    },
  }
}
