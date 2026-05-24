/** 游资语录库：{ text, author? }，有 author 时首页展示署名 */

const QUOTES = [
  { text: '买在分歧，卖在一致' },
  { text: '不必求每天都有机会，而是识别不该出手的日子' },
  { text: '龙空龙：等待识别不该出手的日子' },
  { text: '弱水三千，只取一瓢' },
  { text: '顺势而为，不与大势为敌' },
  { text: '宁可错过，不可做错' },
  { text: '高手死于抄底，新手死于追高' },
  { text: '会买的是徒弟，会卖的是师傅' },
  { text: '涨停敢死，跌停敢空，震荡敢睡' },
  { text: '知行合一，方得始终' },
  { text: '你若是游资高手，定知龙头不凡，引领板块风云' },
  { text: '它一呼百应，小弟紧跟，共谱股市华章' },
  { text: '莫被杂毛迷眼，心守周期循环' },
  { text: '他们深知，投资是场等待的游戏，复利源于不断复制成熟模式' },
  { text: '游资大佬们几年如一日，等待并复制自己的体系，稳健复利' },
  { text: '你或许已洞悉交易秘诀，但实践之路漫漫，知与行间的鸿沟，需以心性为桥，方能跨越至合一之境' },
  { text: '你应专注模式内交易，避免盲目出击，看不懂、没把握的，一律不做' },
  { text: '每一刻自问，出手亦自省，此交易是否遵循模式' },
  { text: '卖出须守四律，达标即止盈止损。日进斗金非梦' },
  { text: '月盈十者众，而年稳盈者稀。交易如马拉松' },
  { text: '不明局势时，静观其变' },
  { text: '悟道之路漫漫，心法需细品' },
  { text: '非核心勿恋，备选即可' },
  { text: '龙头之舞，静待时机' },
  { text: '若遇明主升浪，便无需再寻杂毛反弹' },
  { text: '遇主线明朗之时，无需再念支线纷扰之好' },
  { text: '既然已握市场之选，又何须强求自我挖掘' },
  { text: '市场风云变幻，情绪起落无常，连板不易，轻仓为佳' },
  { text: '决断时刻须果敢，扛单拖延只会痛，人性贪念需克制' },
  { text: '投资路上，心态为王，敢于决断，过往不恋' },
  { text: '跟随趋势，不妄加猜测。时机成熟再出手，静待花开' }
]

function normalizeQuote(item) {
  if (!item) return { text: '', author: '' }
  if (typeof item === 'string') return { text: item.trim(), author: '' }
  return {
    text: String(item.text || '').trim(),
    author: String(item.author || '').trim()
  }
}

function formatQuoteText(text) {
  const t = String(text || '').trim()
  if (!t) return ''
  if (/[。！？；…]$/.test(t)) return t
  return `${t}。`
}

function getDisplayLevel(score) {
  const s = Number(score) || 0
  if (s >= 90) return { label: '狂热', class: 'frenzy', color: '#cf1322' }
  if (s >= 80) return { label: '高潮', class: 'climax', color: '#ff4d4f' }
  if (s >= 60) return { label: '偏乐观', class: 'optimistic', color: '#ff4d4f' }
  if (s >= 40) return { label: '中性', class: 'neutral', color: '#faad14' }
  if (s >= 20) return { label: '偏谨慎', class: 'caution', color: '#52c41a' }
  return { label: '冰点', class: 'cold', color: '#1890ff' }
}

function randomQuote() {
  return normalizeQuote(QUOTES[Math.floor(Math.random() * QUOTES.length)])
}

function dailyQuote(dateStr) {
  if (!dateStr) return randomQuote()
  let hash = 0
  const s = String(dateStr)
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash) + s.charCodeAt(i)
    hash |= 0
  }
  return normalizeQuote(QUOTES[Math.abs(hash) % QUOTES.length])
}

function getQuoteCharset(quotes = QUOTES) {
  const { QUOTE_EXTRA_CHARS } = require('./quoteFont')
  const text = quotes.map(q => {
    const item = normalizeQuote(q)
    return item.text + item.author
  }).join('') + QUOTE_EXTRA_CHARS
  return Array.from(new Set(text.split(''))).join('')
}

module.exports = {
  getDisplayLevel,
  randomQuote,
  dailyQuote,
  normalizeQuote,
  formatQuoteText,
  QUOTES,
  getQuoteCharset
}
