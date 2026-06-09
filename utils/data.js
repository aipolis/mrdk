const PRIMARY = '#FF4D4F'
const { getDisplayLevel } = require('./theme')

function getSentimentLevel(score) {
  const level = require('./theme').getDisplayLevel(score)
  const signal = score >= 55 ? '强' : score >= 35 ? '中' : score >= 15 ? '弱' : '极弱'
  return { label: level.label, color: level.color, signal }
}

function getPositionAdvice(score) {
  if (score <= 14) return { percent: 0, label: '', desc: '综合情绪极弱，盘面偏冷' }
  if (score >= 61) return { percent: 75, label: '', desc: '综合情绪偏强，接力结构尚可' }
  if (score >= 41) return { percent: 50, label: '', desc: '综合情绪中性偏暖，注意分化' }
  if (score >= 21) return { percent: 20, label: '', desc: '综合情绪偏谨慎，短线结构一般' }
  return { percent: 0, label: '', desc: '综合情绪偏弱，宜控节奏' }
}

const yesterdayMock = [
  { key: 'height', label: '连板高度', value: '3板', yesterday: '4板', trend: 'down' },
  { key: 'limitUp', label: '涨停家数', value: '58', yesterday: '82', trend: 'down' },
  { key: 'seal', label: '封板率', value: '63%', yesterday: '71%', trend: 'down' },
  { key: 'promote', label: '晋级率', value: '23%', yesterday: '31%', trend: 'down' },
  { key: 'limitDown', label: '跌停家数', value: '12', yesterday: '8', trend: 'up' },
  { key: 'break', label: '炸板率', value: '37%', yesterday: '29%', trend: 'up' },
  { key: 'oneWord', label: '一字板', value: '12', yesterday: '18', trend: 'down' },
  { key: 'volume', label: '市场量能', value: '8232亿', yesterday: '7654亿', trend: 'up' },
  {
    key: 'advance',
    label: '上涨家数',
    value: '3582',
    yesterday: '2367',
    advance_up: 3582,
    prev_advance_up: 2367,
    trend: 'up'
  }
]

const peripheralMock = [
  { key: 'ftseA50', label: '富时A50指数', price: '13852', chgText: '+0.62%', up: true, trend: 'up' },
  { key: 'sp500', label: '标普500', price: '5312', chgText: '-0.32%', up: false, trend: 'down' },
  { key: 'cnh', label: '离岸人民币', price: '7.245', chgText: '+0.08%', up: true, trend: 'up' }
]

const auctionMock = [
  { key: 'auctionOneWord', label: '竞价一字板', value: '8', yesterday: '12', trend: 'down' },
  { key: 'auctionVolume', label: '竞价量能', value: '412亿', yesterday: '388亿', trend: 'up' },
  { key: 'yesterdayFirst', label: '昨日首板竞价涨幅', value: '+2.18%', yesterday: '+1.05%', trend: 'up', up: true },
  { key: 'yesterdayMulti', label: '昨日连板竞价涨幅', value: '+0.86%', yesterday: '+1.42%', trend: 'down', up: true },
  { key: 'recentMulti', label: '最近多板竞价涨幅', value: '+3.25%', yesterday: '+2.08%', trend: 'up', up: true },
  { key: 'top10AuctionChg', label: '昨日成交额前10平均竞价涨幅', value: '+1.85%', yesterday: '+1.12%', trend: 'up', up: true }
]

const intradayMock = [
  { key: 'sseIndex', label: '上证涨跌', value: '+0.42%', yesterday: '-0.18%', trend: 'up', up: true },
  { key: 'upRatio', label: '上涨占比', value: '59.1%', yesterday: '52.9%', trend: 'up' },
  { key: 'limitUpLive', label: '实时涨停', value: '52', yesterday: '58', trend: 'down' },
  { key: 'limitDownLive', label: '实时跌停', value: '8', yesterday: '12', trend: 'down' },
  { key: 'marketVolumeLive', label: '全市量能', value: '8232亿 +5.2%', yesterday: '7821亿', trend: 'up', up: true },
  { key: 'top10AvgChgLive', label: 'T-1成交额前10平均涨幅', value: '+1.85%', yesterday: '+0.62%', trend: 'up', up: true },
  { key: 'promoteLive', label: 'T-1日涨停晋级率', value: '28%', yesterday: '23%', trend: 'up' },
  { key: 'breakLive', label: '实时炸板率', value: '32%', yesterday: '37%', trend: 'down' }
]

const homeData = {
  adviceDate: '2026-05-22',
  refDate: '2026-05-22',
  generatedAt: '昨日 15:00 更新',
  generatedAtLabel: '昨日 15:00 更新',
  generatedAtTime: '15:00',
  isReportReady: true,
  dailyQuote: '买在分歧，卖在一致',
  score: 28,
  baselineScore: 28,
  liveScore: 35,
  displayScore: 35,
  scoreMode: 'live',
  displayLevel: '偏谨慎',
  levelClass: 'caution',
  levelLabel: '偏谨慎',
  longkongSignal: '弱',
  positionPercent: 20,
  positionLabel: '',
  positionDesc: '昨日情绪偏谨慎，短线结构一般',
  emptyWarning: false,
  emptyReasons: [],
  grid9: yesterdayMock,
  peripheral: peripheralMock,
  auction: auctionMock,
  intraday: intradayMock,
  indicatorSections: [
    { id: 'yesterday', title: '昨日情绪概览', meta: '05-21 15:00 更新', layout: 'grid3', cols: 3, items: yesterdayMock },
    { id: 'peripheral', title: '外围情绪及指数', meta: '05-22 09:15 更新', layout: 'row3', cols: 3, items: peripheralMock },
    { id: 'auction', title: '今日竞价情绪', meta: '05-22 09:15 更新', layout: 'grid3', cols: 3, items: auctionMock },
    { id: 'intraday', title: '盘中实时情绪', meta: '05-22 10:32 更新', layout: 'grid3', cols: 3, items: intradayMock }
  ],
  overview: peripheralMock,
  foreignCards: [],
  indicators: [],
  trend: [
    { date: '05-09', score: 42 },
    { date: '05-12', score: 48 },
    { date: '05-13', score: 51 },
    { date: '05-14', score: 45 },
    { date: '05-15', score: 52 },
    { date: '05-16', score: 38 },
    { date: '05-17', score: 61 },
    { date: '05-18', score: 55 },
    { date: '05-19', score: 35 },
    { date: '05-20', score: 28 }
  ]
}

const historyData = Array.from({ length: 30 }, (_, i) => {
  const day = 30 - i
  const score = Math.round(20 + Math.sin(day * 0.5) * 25 + (day % 7) * 2)
  const lv = getDisplayLevel(score)
  const level = lv.label
  const levelClass = lv.class
  const chg = Math.round((Math.sin(day * 0.3) * 1.5 - 0.2) * 100) / 100
  return {
    date: `2026-05-${String(day).padStart(2, '0')}`,
    score,
    level,
    levelClass,
    indexChg: chg,
    indexChgText: `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%`,
    indexUp: chg >= 0
  }
})

module.exports = {
  PRIMARY,
  getSentimentLevel,
  getPositionAdvice,
  homeData,
  historyData,
  yesterdayMock,
  peripheralMock,
  auctionMock
}
