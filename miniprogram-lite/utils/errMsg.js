/** 把 wx / API 各类错误转成可读字符串 */
function formatErrMsg(err, fallback) {
  if (!err) return fallback || '加载失败'
  if (typeof err === 'string') return err
  const msg = err.message || err.errMsg || err.msg
  if (typeof msg === 'string' && msg) {
    if (/url not in domain|不在以下 request 合法域名/i.test(msg)) {
      return '网络域名未配置，请在开发者工具勾选「不校验合法域名」'
    }
    return msg
  }
  if (typeof msg === 'object' && msg) {
    try {
      return JSON.stringify(msg)
    } catch (e) {
      /* ignore */
    }
  }
  try {
    return JSON.stringify(err)
  } catch (e) {
    return fallback || '加载失败'
  }
}

module.exports = { formatErrMsg }
