/** 分数 → 展示色，7 档色阶（与 web trendDraw.js 一致） */
function getScoreColor(score, levelClass, levelColor) {
  if (levelColor) return levelColor
  const s = Number(score) || 0
  if (levelClass === 'frenzy')                         return '#cf1322'
  if (levelClass === 'climax')                         return '#cf1322'
  if (levelClass === 'optimistic')                     return '#ff4d4f'
  if (levelClass === 'neutral')                        return '#faad14'
  if (levelClass === 'caution')                        return '#52c41a'
  if (levelClass === 'weak' || levelClass === 'cold')  return '#38bdf8'
  // 按分数区间回退
  if (s >= 90) return '#820014'
  if (s >= 75) return '#cf1322'
  if (s >= 60) return '#ff4d4f'
  if (s >= 50) return '#faad14'
  if (s >= 40) return '#52c41a'
  if (s >= 30) return '#38bdf8'
  return '#94a3b8'
}

module.exports = { getScoreColor }
