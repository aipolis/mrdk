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

const RISK_MULTIPLIERS = {
  none: 1.0,
  caution: 0.8,
  warning: 0.5,
  critical: 0.0,
}

function roundPosition(value) {
  return Math.max(0, Math.min(100, Math.round(Number(value) / 10) * 10))
}

function floorPosition(value) {
  return Math.max(0, Math.min(100, Math.floor(Number(value) / 10) * 10))
}

export function basePositionFromScore(score) {
  const s = Number(score) || 0
  return roundPosition(Math.max(0, Math.min(70, Math.max(0, (s - 35) * 1.2))))
}

function applyRiskToPosition(position, riskLevel) {
  const mult = RISK_MULTIPLIERS[riskLevel] ?? 1.0
  return floorPosition(Number(position) * mult)
}

function stabilizePosition(target, options = {}) {
  const {
    previousPosition = null,
    increaseConfirmations = 0,
    scoreMode = 'baseline',
    emptyWarning = false,
  } = options
  let nextTarget = roundPosition(target)
  if (emptyWarning) return { percent: 0, stability: 'critical', confirmations: 0 }
  if (previousPosition == null) {
    return { percent: nextTarget, stability: 'initial', confirmations: 0 }
  }
  const previous = roundPosition(previousPosition)
  if (nextTarget < previous) {
    return { percent: Math.max(nextTarget, previous - 10), stability: 'reduced', confirmations: 0 }
  }
  if (nextTarget === previous) {
    return { percent: previous, stability: 'unchanged', confirmations: 0 }
  }
  if (scoreMode === 'live') {
    return { percent: previous, stability: 'live_hold', confirmations: 0 }
  }
  const confirmations = Number(increaseConfirmations || 0) + 1
  if (confirmations < 2) {
    return { percent: previous, stability: 'confirming', confirmations }
  }
  return { percent: Math.min(nextTarget, previous + 10), stability: 'increased', confirmations: 0 }
}

function isTenStep(value) {
  if (value == null || value === '') return true
  const n = Number(value)
  return Number.isFinite(n) && n % 10 === 0
}

/** 线上旧版 API 会把仓位连续 //2，出现 5、2 等非 10% 档位。 */
export function isLegacyPositionPayload(data) {
  if (data?.cacheWarmup) return false
  if (data?.basePositionPercent != null) return false
  if (!isTenStep(data?.positionPercent)) return true
  if (data?.baselinePositionPercent != null && !isTenStep(data?.baselinePositionPercent)) return true
  if (data?.positionTargetPercent != null && !isTenStep(data?.positionTargetPercent)) return true
  return false
}

function resolveVolatilityMultiplier(data) {
  const direct = Number(data?.volatilityMultiplier)
  if (Number.isFinite(direct) && direct > 0) return direct
  const proxy = data?.volatilityProxy?.multiplier ?? data?.baselineVolatilityProxy?.multiplier
  const parsed = Number(proxy)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1.0
}

function resolveRiskMultiplier(data, riskLevel) {
  const direct = Number(data?.riskMultiplier)
  if (Number.isFinite(direct) && direct >= 0) return direct
  return RISK_MULTIPLIERS[riskLevel] ?? 1.0
}

/** 与 server/sentiment.py 一致的仓位展示计算。 */
export function resolvePositionDisplay(data) {
  if (data?.cacheWarmup) {
    const score = Number(data?.displayScore ?? data?.score ?? 0)
    const percent = Number.isFinite(score) && score > 0 ? basePositionFromScore(score) : null
    return {
      percent,
      targetPercent: percent,
      basePercent: percent,
      riskMultiplier: null,
      volatilityMultiplier: null,
      stability: 'warmup',
      reasons: [],
      legacyFixed: false,
    }
  }

  if (data?.emptyWarning) {
    return {
      percent: 0,
      targetPercent: 0,
      basePercent: basePositionFromScore(data?.baselineScore ?? data?.score),
      riskMultiplier: resolveRiskMultiplier(data, data?.riskLevel || 'none'),
      volatilityMultiplier: resolveVolatilityMultiplier(data),
      stability: data?.positionStability || 'critical',
      reasons: Array.isArray(data?.positionReasons) ? data.positionReasons : [],
      legacyFixed: false,
    }
  }

  const hasNewPayload = data?.basePositionPercent != null && !isLegacyPositionPayload(data)
  if (hasNewPayload) {
    const percent = Number(data.positionPercent)
    return {
      percent: Number.isFinite(percent) ? roundPosition(percent) : null,
      targetPercent: Number(data?.positionTargetPercent ?? data?.positionPercent),
      basePercent: Number(data?.basePositionPercent),
      riskMultiplier: resolveRiskMultiplier(data, data?.riskLevel || 'none'),
      volatilityMultiplier: resolveVolatilityMultiplier(data),
      stability: data?.positionStability || 'unchanged',
      reasons: Array.isArray(data?.positionReasons) ? data.positionReasons : [],
      legacyFixed: false,
    }
  }

  const baselineScore = Number(data?.baselineScore ?? data?.score ?? 0)
  const riskLevel = data?.riskLevel || data?.baselineRiskLevel || 'none'
  const basePercent = basePositionFromScore(baselineScore)
  const riskMultiplier = resolveRiskMultiplier(data, riskLevel)
  const volatilityMultiplier = resolveVolatilityMultiplier(data)
  const riskAdjusted = applyRiskToPosition(basePercent, riskLevel)
  const targetPercent = floorPosition(riskAdjusted * volatilityMultiplier)
  const stabilized = stabilizePosition(targetPercent, {
    previousPosition: isLegacyPositionPayload(data) ? null : data?.positionPercent,
    increaseConfirmations: data?.positionConfirmations,
    scoreMode: data?.scoreMode || 'baseline',
    emptyWarning: false,
  })
  const reasons = Array.isArray(data?.positionReasons) && data.positionReasons.length
    ? data.positionReasons
    : (data?.emptyReasons || [])

  return {
    percent: stabilized.percent,
    targetPercent,
    basePercent,
    riskMultiplier,
    volatilityMultiplier,
    stability: stabilized.stability,
    confirmations: stabilized.confirmations,
    reasons,
    legacyFixed: isLegacyPositionPayload(data),
  }
}
