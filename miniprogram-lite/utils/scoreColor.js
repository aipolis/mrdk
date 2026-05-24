/** 分数 → 展示色（龙=红 / 中=橙 / 空=蓝，与设计稿一致） */
function getScoreColor(score, levelClass, levelColor) {
  if (levelColor) return levelColor
  const s = Number(score) || 0
  if (levelClass === 'frenzy') return '#e63838'
  if (levelClass === 'climax' || levelClass === 'optimistic') return '#e63838'
  if (levelClass === 'neutral') return '#f5a60a'
  if (levelClass === 'caution') return '#f5a60a'
  if (levelClass === 'cold') return '#91d1ed'
  if (s > 70) return '#e63838'
  if (s >= 30) return '#f5a60a'
  return '#91d1ed'
}

module.exports = { getScoreColor }
