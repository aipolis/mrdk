/**
 * 明日当空 · 环境配置
 *
 * 【本地开发】
 *   API_BASE: 'http://127.0.0.1:8000'
 *   开发者工具勾选「不校验合法域名」
 *
 * 【微信云托管 · 方式A 公网 HTTPS】（推荐，简单）
 *   1. 云托管控制台复制「公网访问地址」
 *   2. 填入 API_BASE
 *   3. 微信公众平台 → 服务器域名 → request / uploadFile 都填该域名
 *
 * 【微信云托管 · 方式B 云调用】（免配 request 域名）
 *   USE_CLOUD_CALL: true
 *   HTTP_FALLBACK: false（默认，避免未配域名时报错）
 *   填写 CLOUD_ENV、CLOUD_SERVICE
 *   需在 app.js 中 wx.cloud.init
 *   若开启 HTTP_FALLBACK，须把 API_BASE 域名加入 request 合法域名
 */
module.exports = {
  // 正式上线推荐：云调用（无需配置 request 合法域名）
  USE_CLOUD_CALL: true,

  // 云调用超时后是否回退 HTTPS（须已在公众平台配置 request 合法域名）
  HTTP_FALLBACK: true,

  // false：云调用优先（免配 request 域名；最小实例=1 后稳定）
  // true：HTTPS 优先（须公众平台配置合法域名，且默认测试域名可能受限）
  HTTP_PREFER_DIRECT: false,

  /** 云调用超时（毫秒） */
  CLOUD_TIMEOUT_MS: 60000,
  CLOUD_RETRY: 1,

  /** HTTPS 超时（毫秒，微信上限 60000） */
  HTTP_TIMEOUT_MS: 60000,

  /** 启动预取超时（毫秒，失败则用本地缓存，后台再刷） */
  PREFETCH_TIMEOUT_MS: 20000,

  /** 首页主动拉取超时（毫秒；云调用冷启动可能较慢） */
  HOME_FETCH_TIMEOUT_MS: 45000,

  // 公网地址：OCR 上传 + 可选 HTTPS 回退（须与公众平台 request 域名一致）
  API_BASE: 'https://mingri-api-260693-8-1435576840.sh.run.tcloudbase.com',

  // 云开发环境 ID（云托管控制台可见）
  CLOUD_ENV: 'prod-d3g2pxi63c4a4516b',
  CLOUD_SERVICE: 'mingri-api',

  // 微信公众平台 → 订阅消息 → 模板 ID
  SUBSCRIBE_TEMPLATES: {
    // 市场情绪更新（thing7=策略类型 character_string2=关键数据 time3=时间 thing12=温馨提示）
    sentimentDaily: '2PJYcWlocC15xg2W7YDLzT5B1Qff5Hc24O-mLEsw4tU',
    // 暂未单独申请个人信号模板，与每日推送共用同一模板
    emptyAlert: '2PJYcWlocC15xg2W7YDLzT5B1Qff5Hc24O-mLEsw4tU'
  },

  // 服务端发送订阅消息时的字段名映射（与模板一致）
  SUBSCRIBE_FIELD_KEYS: {
    strategy: 'thing7',
    keyData: 'character_string2',
    time: 'time3',
    tips: 'thing12'
  },

  /** 预览固定分数：设为 null 则使用接口真实数据；调试完改回 null */
  PREVIEW_SCORE: null,

  /** 语录字体：wenkai 霞鹜文楷 | zcool 站酷快乐体 | smiley 得意黑 */
  QUOTE_FONT: 'wenkai'
}
