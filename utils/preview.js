const { getDisplayLevel } = require('./theme')
const { getPositionAdvice } = require('./data')

/** 每次调用时读取 config，避免改分数后仍用旧缓存 */
function getPreviewScore() {
  const { PREVIEW_SCORE } = require('./config')
  if (PREVIEW_SCORE == null || PREVIEW_SCORE === '') return null
  const n = Number(PREVIEW_SCORE)
  return Number.isNaN(n) ? null : n
}

function withPreviewScore(data) {
  const score = getPreviewScore()
  if (score == null) return data

  const level = getDisplayLevel(score)
  const advice = getPositionAdvice(score)
  let trend = data.trend
  if (Array.isArray(trend) && trend.length) {
    trend = trend.slice()
    const last = trend[trend.length - 1]
    trend[trend.length - 1] = { ...last, score }
  }

  return {
    ...data,
    score,
    baselineScore: score,
    displayScore: score,
    liveScore: null,
    scoreMode: 'baseline',
    trend,
    displayLevel: level.label,
    levelClass: level.class,
    levelLabel: level.label,
    positionPercent: advice.percent,
    positionLabel: advice.label,
    positionDesc: advice.desc,
    emptyWarning: advice.percent === 0
  }
}

module.exports = { getPreviewScore, withPreviewScore }
