/** 龙空龙状态灯：分数段与表盘一致，颜色随展示分 */

const { getDisplayLevel } = require('./theme')

const STEPS = [
  { state: 'dragon', label: '龙' },
  { state: 'repair', label: '较强' },
  { state: 'retreat', label: '较弱' },
  { state: 'empty', label: '空' },
]

function scoreToLongkongState(score, emptyWarning = false) {
  if (emptyWarning) {
    return { state: 'empty', label: '空', desc: '风险偏高，宜控节奏' }
  }
  const s = Number(score) || 0
  if (s > 70) {
    return { state: 'dragon', label: '龙', desc: '接力结构较强' }
  }
  if (s >= 50) {
    return { state: 'repair', label: '较强', desc: '有较强迹象，待确认' }
  }
  if (s >= 30) {
    return { state: 'retreat', label: '较弱', desc: '接力偏弱' }
  }
  return { state: 'empty', label: '空', desc: '风险偏高，宜控节奏' }
}

function resolveLongkongState(data) {
  const score = Number((data && (data.displayScore != null ? data.displayScore : data.score)) || 0) || 0
  const emptyWarning = !!(data && data.emptyWarning)
  const lk = scoreToLongkongState(score, emptyWarning)
  return {
    ...lk,
    steps: STEPS.map((step) => ({
      ...step,
      active: step.state === lk.state,
    })),
  }
}

function resolveLongkongTone(data) {
  const score = Number((data && (data.displayScore != null ? data.displayScore : data.score)) || 0) || 0
  return getDisplayLevel(score)
}


function buildLongkongHeroText(data, lk) {
  const levelLabel = String((data && (data.levelLabel || data.displayLevel)) || '').trim()
  const positionDesc = String((data && data.positionDesc) || '').trim()
  const lkDesc = String((lk && lk.desc) || '').trim()
  const desc = positionDesc || lkDesc
  return { levelLabel, desc }
}

module.exports = {
  STEPS,
  scoreToLongkongState,
  resolveLongkongState,
  resolveLongkongTone,
  buildLongkongHeroText,
}
