/** 
 * API_BASE 配置策略：优先级从高到低
 * 1. 运行时注入：window.__API_BASE__ （Cloudflare/浏览器可设置）
 * 2. localStorage key: mrdk_api_base （用户配置）
 * 3. 环境变量：process.env.VITE_API_BASE （构建时）
 * 4. 默认值（线上生产地址）
 */
function resolveApiBase() {
  if (typeof window !== 'undefined' && window.__API_BASE__) {
    return window.__API_BASE__
  }
  if (typeof localStorage !== 'undefined') {
    const stored = localStorage.getItem('mrdk_api_base')
    if (stored && stored.trim()) return stored.trim()
  }
  if (typeof process !== 'undefined' && process.env && process.env.VITE_API_BASE) {
    return process.env.VITE_API_BASE
  }
  return 'https://mingri-api-260693-8-1435576840.sh.run.tcloudbase.com'
}

export const API_BASE = resolveApiBase()
export { resolveApiBase }

export const FETCH_TIMEOUT_MS = 20000

/** 首页自动刷新间隔（毫秒），与后端盘中 2 分钟节奏一致 */
export const AUTO_REFRESH_MS = 2 * 60 * 1000

/** 竞价窗口 9:15–9:26 刷新间隔（一字 / 板块 Top10） */
export const AUCTION_REFRESH_MS = 20 * 1000

/** 量能异动 9:20–9:26 刷新间隔 */
export const VOLUME_SURGE_REFRESH_MS = 30 * 1000

export function resolveAutoRefreshMs(now = new Date()) {
  const hm = now.getHours() * 60 + now.getMinutes()
  if (hm >= 9 * 60 + 15 && hm < 9 * 60 + 26) return AUCTION_REFRESH_MS
  return AUTO_REFRESH_MS
}

/** 竞价详情页轮询：竞价窗口内 20s，其余 5 分钟 */
export function resolveAuctionDetailPollMs(now = new Date()) {
  const hm = now.getHours() * 60 + now.getMinutes()
  if (hm >= 9 * 60 + 15 && hm < 9 * 60 + 26) return AUCTION_REFRESH_MS
  return 5 * 60 * 1000
}

/** 量能异动轮询：9:20–9:26 每 30s，其余不轮询 */
export function resolveVolumeSurgePollMs(now = new Date()) {
  const hm = now.getHours() * 60 + now.getMinutes()
  if (hm >= 9 * 60 + 20 && hm < 9 * 60 + 26) return VOLUME_SURGE_REFRESH_MS
  return 0
}

/**
 * 开发环境设置 API 地址
 * 在浏览器控制台执行：localStorage.setItem('mrdk_api_base', 'http://127.0.0.1:8000')
 * 然后刷新页面，或者直接 window.__API_BASE__ = 'http://127.0.0.1:8000'
 */
export function setApiBase(url) {
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem('mrdk_api_base', url)
  }
  if (typeof window !== 'undefined') {
    window.__API_BASE__ = url
  }
}
