/** 根据首页情绪数据生成订阅消息预览（与后端 subscribe_msg 逻辑一致） */



function clip(text, max) {

  const s = String(text || '').trim()

  if (s.length <= max) return s

  return s.slice(0, max - 1) + '…'

}



function tipsFromSentiment(score, empty, emptyReasons) {

  if (empty && emptyReasons && emptyReasons.length) {

    return clip(emptyReasons.slice(0, 2).join('；'), 20)

  }

  if (empty || score <= 14) return clip('昨日情绪极弱，盘面偏冷', 20)
  if (score < 50) return clip('盘中情绪走弱，低于50分', 20)

  if (score >= 61) return clip('昨日情绪偏强，注意分歧', 20)

  if (score >= 41) return clip('昨日情绪偏暖，结构尚可', 20)

  if (score >= 21) return clip('昨日情绪偏谨慎', 20)

  return clip('昨日情绪偏弱', 20)

}



function buildSubscribePreview(data) {

  const score = data.displayScore != null ? data.displayScore : (data.score || 0)

  const level = data.displayLevel || data.levelLabel || '中性'

  const empty = !!data.emptyWarning

  const reasons = data.emptyReasons || []

  const adviceDate = data.adviceDate || data.date || ''



  const strategy = empty

    ? clip('龙空龙·个人信号', 20)

    : clip(`市场情绪·${level}`, 20)

  const keyData = clip(`情绪${score}分·${level}`, 32)



  return {

    strategy,

    keyData,

    time: `${adviceDate} 09:15`,

    tips: tipsFromSentiment(score, empty, reasons)

  }

}



module.exports = { buildSubscribePreview }

