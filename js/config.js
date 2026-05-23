/** 部署后可在 Cloudflare Pages 环境变量中设置 VITE_API_BASE（构建时）或直接改此默认值 */
export const API_BASE = (
  typeof window !== 'undefined' && window.__API_BASE__
) || 'https://mingri-api-260693-8-1435576840.sh.run.tcloudbase.com'

export const FETCH_TIMEOUT_MS = 45000

/** 首页自动刷新间隔（毫秒），与后端盘中 2 分钟节奏一致 */
export const AUTO_REFRESH_MS = 2 * 60 * 1000
