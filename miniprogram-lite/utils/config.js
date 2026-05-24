/** 明日当空 Lite · 与完整版共用同一云托管后端 */
module.exports = {
  USE_CLOUD_CALL: true,
  HTTP_FALLBACK: true,
  HTTP_PREFER_DIRECT: false,
  CLOUD_TIMEOUT_MS: 60000,
  CLOUD_RETRY: 1,
  HTTP_TIMEOUT_MS: 60000,
  HOME_FETCH_TIMEOUT_MS: 45000,

  API_BASE: 'https://mingri-api-260693-8-1435576840.sh.run.tcloudbase.com',
  CLOUD_ENV: 'prod-d3g2pxi63c4a4516b',
  CLOUD_SERVICE: 'mingri-api',

  SUBSCRIBE_TEMPLATES: {
    sentimentDaily: '2PJYcWlocC15xg2W7YDLzT5B1Qff5Hc24O-mLEsw4tU',
  },

  SUBSCRIBE_FIELD_KEYS: {
    strategy: 'thing7',
    keyData: 'character_string2',
    time: 'time3',
    tips: 'thing12',
  },

  APP_TAGLINE: '识别下雨天，下雨天少出门',

  /** 首页页头 · 固定文案 */
  APP_TITLE: '明日当空？',
  APP_SUBTITLE: '不怕错过，就怕做错，帮你识别下雨天！',

  /** 游资语录区 · 固定两条，不随接口变化 */
  QUOTE_SECTION: {
    title: '与君共勉',
    moreLabel: '更多 →',
    items: [
      {
        theme: 'blue',
        text: '不怕错过，就怕做错。不出门的时候，就在家修炼。',
        author: '—— 养家心法',
      },
      {
        theme: 'yellow',
        text: '雨天不出门，是为了晴天走更远的路。耐心等待窗口期。',
        author: '—— 龙空龙心法',
      },
    ],
  },
}
