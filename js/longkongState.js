/** 龙空龙状态灯：分数段与表盘一致，颜色随展示分 */

import { getDisplayLevel } from './theme.js'

export const LONGKONG_STATE_STEPS = [
  { state: 'dragon', label: '龙' },
  { state: 'repair', label: '修复' },
  { state: 'retreat', label: '退潮' },
  { state: 'empty', label: '空' },
]

export const GAUGE_LEVEL_CLASSES = [
  'frenzy', 'climax', 'optimistic', 'neutral', 'caution', 'weak', 'cold',
]

/** 龙 >70 · 修复 50–70 · 退潮 30–50 · 空 <30；龙空风险强制为空 */
export function scoreToLongkongState(score, emptyWarning = false) {
  if (emptyWarning) {
    return { state: 'empty', label: '空', desc: '风险偏高，宜控节奏' }
  }
  const s = Number(score) || 0
  if (s > 70) {
    return { state: 'dragon', label: '龙', desc: '接力结构较强' }
  }
  if (s >= 50) {
    return { state: 'repair', label: '修复', desc: '有修复迹象，待确认' }
  }
  if (s >= 30) {
    return { state: 'retreat', label: '退潮', desc: '接力偏弱' }
  }
  return { state: 'empty', label: '空', desc: '风险偏高，宜控节奏' }
}

export function resolveLongkongState(data) {
  const score = Number(data?.displayScore ?? data?.score ?? 0) || 0
  const emptyWarning = !!data?.emptyWarning
  return scoreToLongkongState(score, emptyWarning)
}

export function setGaugeLevelClass(el, levelClass) {
  if (!el) return
  GAUGE_LEVEL_CLASSES.forEach((c) => el.classList.remove(c))
  if (levelClass) el.classList.add(levelClass)
}

export function renderLongkongLightsHtml(activeState, levelClass = 'neutral', riskLevel = 'none') {
  return LONGKONG_STATE_STEPS.map((step) => {
    const active = step.state === activeState
    const riskClass = active && (riskLevel === 'warning' || riskLevel === 'caution')
      ? ` risk-${riskLevel}` : ''
    const tone = active ? ` is-active ${levelClass}${riskClass}` : ''
    return `<div class="longkong-light${tone}" data-state="${step.state}" role="listitem">
      <span class="longkong-light-dot" aria-hidden="true"></span>
      <span class="longkong-light-label">${step.label}</span>
    </div>`
  }).join('')
}

export function resolveLongkongTone(data) {
  const score = Number(data?.displayScore ?? data?.score ?? 0) || 0
  return getDisplayLevel(score)
}


export function buildLongkongHeroText(data, lk) {
  const levelLabel = String(data?.levelLabel || data?.displayLevel || '').trim()
  const positionDesc = String(data?.positionDesc || '').trim()
  const lkDesc = String(lk?.desc || '').trim()
  const desc = positionDesc || lkDesc
  return { levelLabel, desc }
}

export function normalizeRiskReason(reason) {
  const raw = String(reason || '').trim()
  if (!raw) return '接力环境偏谨慎'
  const promote = raw.match(/晋级率(?:仅|只有)?\s*(\d+(?:\.\d+)?)%/)
  if (promote) return `昨日涨停股今日晋级率仅 ${promote[1]}%，也就是昨日涨停股中今天继续涨停的比例偏低`
  const breakRate = raw.match(/炸板率(?:高达|达到|为)?\s*(\d+(?:\.\d+)?)%/)
  if (breakRate) return `炸板率 ${breakRate[1]}%，封板稳定性不足`
  return raw
}

export function buildRiskCopy(data) {
  if (!data?.emptyWarning) return null
  const reason = normalizeRiskReason((data.emptyReasons && data.emptyReasons[0]) || '')
  return {
    desc: '分数中性，但接力晋级偏弱',
    tip: `复盘提示：${reason}。打板少做、精选，等更强确认。`,
  }
}
