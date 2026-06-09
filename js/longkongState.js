/** 龙空龙状态灯：分数段与表盘一致，颜色随展示分 */

import { getDisplayLevel } from './theme.js'

export const LONGKONG_STATE_STEPS = [
  { state: 'dragon', label: '龙' },
  { state: 'repair', label: '较强' },
  { state: 'retreat', label: '较弱' },
  { state: 'empty', label: '空' },
]

export const GAUGE_LEVEL_CLASSES = [
  'frenzy', 'climax', 'optimistic', 'neutral', 'caution', 'weak', 'cold',
]

/** 龙 >75 · 较强 60–75 · 较弱 40–60 · 空 <40；龙空风险强制为空 */
export function scoreToLongkongState(score, emptyWarning = false) {
  if (emptyWarning) {
    return { state: 'empty', label: '空', desc: '风险偏高，宜控节奏' }
  }
  const s = Number(score) || 0
  if (s > 75) {
    return { state: 'dragon', label: '龙', desc: '接力结构较强' }
  }
  if (s >= 60) {
    return { state: 'repair', label: '较强', desc: '有较强迹象，待确认' }
  }
  if (s >= 40) {
    return { state: 'retreat', label: '较弱', desc: '接力偏弱' }
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
  if (!raw) return ''
  const promote = raw.match(/晋级率(?:仅|只有)?\s*(\d+(?:\.\d+)?)%/)
  if (promote) return `晋级率仅 ${promote[1]}%`
  const breakRate = raw.match(/炸板率(?:高达|达到|为)?\s*(\d+(?:\.\d+)?)%/)
  if (breakRate) return `炸板率 ${breakRate[1]}%`
  const score = raw.match(/(?:盘中|综合)?情绪分\s*(\d+).*低于\s*(\d+)分/)
  if (score) return `情绪分 ${score[1]}，低于 ${score[2]}`
  return raw
    .replace(/[（(]作者复盘[）)]/g, '')
    .replace(/[。；;]+$/g, '')
    .trim()
}

function selectRiskReasons(data) {
  const reasons = (data?.emptyReasons || [])
    .map(normalizeRiskReason)
    .filter(Boolean)
  const concrete = reasons.filter((reason) => /晋级率|炸板率|跌停|连板|溢价/.test(reason))
  return [...new Set([...concrete, ...reasons])].slice(0, 2)
}

export function buildRiskCopy(data) {
  if (!data?.emptyWarning) return null
  const reasons = selectRiskReasons(data)
  const focus = reasons.length ? reasons.join('、') : '接力结构偏弱'
  const action = data?.riskLevel === 'critical'
    ? '减少接力，等待修复'
    : '控制节奏，等待确认'
  return {
    desc: '接力结构偏弱，风险优先',
    tip: `复盘｜重点：${focus}；应对：${action}。`,
  }
}
