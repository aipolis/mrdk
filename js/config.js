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

export const FETCH_TIMEOUT_MS = 45000

/** 首页自动刷新间隔（毫秒），与后端盘中 2 分钟节奏一致 */
export const AUTO_REFRESH_MS = 2 * 60 * 1000

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
