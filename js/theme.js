export const HOME_QUOTE = '不怕错过，就怕做错。不出门的时候，就在家修炼。'

const QUOTES = [
  { text: HOME_QUOTE },
  { text: '不必求每天都有机会，而是识别不该出手的日子' },
  { text: '龙空龙：等待识别不该出手的日子' },
  { text: '弱水三千，只取一瓢' },
  { text: '顺势而为，不与大势为敌' },
  { text: '宁可错过，不可做错' },
  { text: '知行合一，方得始终' },
]

export function getDisplayLevel(score) {
  const s = Number(score) || 0
  if (s >= 90) return { label: '狂热', class: 'frenzy', color: '#cf1322' }
  if (s >= 80) return { label: '高潮', class: 'climax', color: '#ff4d4f' }
  if (s >= 60) return { label: '偏乐观', class: 'optimistic', color: '#ff4d4f' }
  if (s >= 50) return { label: '中性', class: 'neutral', color: '#faad14' }
  if (s >= 40) return { label: '偏谨慎', class: 'caution', color: '#52c41a' }
  if (s >= 30) return { label: '偏冷', class: 'weak', color: '#38bdf8' }
  return { label: '冰点', class: 'cold', color: '#1890ff' }
}

export function dailyQuote(dateStr) {
  if (!dateStr) {
    return QUOTES[Math.floor(Math.random() * QUOTES.length)]
  }
  let hash = 0
  const s = String(dateStr)
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash) + s.charCodeAt(i)
    hash |= 0
  }
  return QUOTES[Math.abs(hash) % QUOTES.length]
}

export function formatHeaderDate() {
  const d = new Date()
  const w = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()]
  const m = d.getMonth() + 1
  const day = d.getDate()
  return `${m}月${day}日 ${w}`
}
