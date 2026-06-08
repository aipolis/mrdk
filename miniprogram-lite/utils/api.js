const {
  API_BASE,
  USE_CLOUD_CALL,
  CLOUD_ENV,
  CLOUD_SERVICE,
  HTTP_FALLBACK,
  HTTP_PREFER_DIRECT,
  CLOUD_TIMEOUT_MS = 60000,
  CLOUD_RETRY = 0,
  HTTP_TIMEOUT_MS = 60000,
  PREFETCH_TIMEOUT_MS = 15000,
  HOME_FETCH_TIMEOUT_MS = 45000
} = require('./config')
const { formatErrMsg } = require('./errMsg')

let cloudInitPromise = null
let _isDevtools = null

/** 开发者工具内云调用 SDK 常不可用，直连 HTTPS 更稳（须勾选不校验合法域名） */
function isDevtoolsEnv() {
  if (_isDevtools != null) return _isDevtools
  try {
    const info = wx.getDeviceInfo ? wx.getDeviceInfo() : wx.getSystemInfoSync()
    _isDevtools = info.platform === 'devtools'
  } catch (e) {
    _isDevtools = false
  }
  return _isDevtools
}

function shouldUseCloudCall() {
  return USE_CLOUD_CALL && CLOUD_ENV && !isDevtoolsEnv()
}

function ensureCloudInit() {
  if (!USE_CLOUD_CALL || !CLOUD_ENV || !wx.cloud) {
    return Promise.resolve(false)
  }
  if (cloudInitPromise) return cloudInitPromise
  cloudInitPromise = new Promise(resolve => {
    try {
      wx.cloud.init({ env: CLOUD_ENV, traceUser: true })
      setTimeout(() => resolve(true), 80)
    } catch (e) {
      resolve(false)
    }
  })
  return cloudInitPromise
}

function parseResponse(res, path) {
  const data = res.data
  if (path === '/api/health' && data && data.status === 'ok') {
    return data
  }
  if (res.statusCode >= 200 && res.statusCode < 300 && data && data.code === 0) {
    return data.data
  }
  const msg = formatErrMsg(data && data.message, `请求失败 ${res.statusCode}`)
  throw new Error(msg || `请求失败 ${res.statusCode}`)
}

function isTimeoutError(err) {
  const msg = String((err && (err.errMsg || err.message)) || err || '')
  return /timeout|timed out/i.test(msg)
}

function cloudCall(path, options = {}) {
  return ensureCloudInit().then(ready => {
    if (!ready || !wx.cloud.callContainer) {
      return Promise.reject(new Error('cloud_not_ready'))
    }
    return new Promise((resolve, reject) => {
      wx.cloud.callContainer({
        config: { env: CLOUD_ENV },
        path,
        method: options.method || 'GET',
        header: {
          'X-WX-SERVICE': CLOUD_SERVICE,
          'Content-Type': 'application/json',
          ...(options.header || {})
        },
        data: options.data || {},
        timeout: options.timeout || CLOUD_TIMEOUT_MS,
        success(res) {
          try {
            resolve(parseResponse(res, path))
          } catch (e) {
            reject(e)
          }
        },
        fail(err) {
          reject(err || new Error('cloud_fail'))
        }
      })
    })
  })
}

function cloudCallWithRetry(path, options = {}, retriesLeft = CLOUD_RETRY) {
  return cloudCall(path, options).catch(err => {
    if (retriesLeft > 0 && isTimeoutError(err)) {
      return cloudCallWithRetry(path, options, retriesLeft - 1)
    }
    throw err
  })
}

function isRetryableError(err) {
  const msg = String((err && (err.errMsg || err.message)) || err || '')
  return isTimeoutError(err)
    || msg.includes('cloud_not_ready')
    || msg.includes('cloud_fail')
    || msg.includes('http_fail')
    || msg.includes('no_api_base')
    || msg.includes('fail')
}

function clampTimeout(ms) {
  const n = Number(ms) || HTTP_TIMEOUT_MS
  return Math.min(Math.max(n, 1000), 60000)
}

function httpRequest(path, options = {}) {
  return new Promise((resolve, reject) => {
    if (!API_BASE) {
      reject(new Error('no_api_base'))
      return
    }
    wx.request({
      url: `${API_BASE}${path}`,
      method: options.method || 'GET',
      data: options.data || {},
      header: options.header || { 'Content-Type': 'application/json' },
      timeout: clampTimeout(options.timeout || HTTP_TIMEOUT_MS),
      success(res) {
        try {
          resolve(parseResponse(res, path))
        } catch (e) {
          reject(e)
        }
      },
      fail(err) {
        reject(err || new Error('http_fail'))
      }
    })
  })
}

function request(path, options = {}) {
  if (!shouldUseCloudCall() || !API_BASE) {
    if (API_BASE) return httpRequest(path, options)
    if (shouldUseCloudCall()) return cloudCallWithRetry(path, options)
    return Promise.reject(new Error('no_api_base'))
  }
  if (options.httpOnly || options.skipFallback) {
    return httpRequest(path, options)
  }
  if (HTTP_FALLBACK && HTTP_PREFER_DIRECT && API_BASE) {
    return httpRequest(path, options).catch(err => {
      if (isRetryableError(err)) {
        return cloudCallWithRetry(path, options)
      }
      throw err
    })
  }
  if (!HTTP_FALLBACK || !API_BASE) {
    return cloudCallWithRetry(path, options)
  }
  return cloudCallWithRetry(path, options).catch(err => {
    if (isRetryableError(err)) {
      return httpRequest(path, options)
    }
    throw err
  })
}

function uploadOcr(filePath) {
  const uploadUrl = `${API_BASE}/api/ocr/position`
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: uploadUrl,
      filePath,
      name: 'file',
      timeout: 90000,
      success(res) {
        try {
          const data = JSON.parse(res.data)
          if (data.code === 0) resolve(data.data)
          else reject(new Error((data.data && data.data.message) || '识别失败'))
        } catch (e) {
          reject(e)
        }
      },
      fail: reject
    })
  })
}

function isCacheWarmingError(err) {
  const msg = String((err && (err.errMsg || err.message)) || err || '')
  return msg.includes('预热') || msg.includes('retryAfterSec')
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function getTodaySentiment(options = {}) {
  const timeout = clampTimeout(options.timeout || HOME_FETCH_TIMEOUT_MS || HTTP_TIMEOUT_MS)
  const httpOnly = options.httpOnly === true || isDevtoolsEnv()
  if (API_BASE && (httpOnly || options.skipFallback)) {
    return httpRequest('/api/sentiment/today', { timeout })
  }
  return request('/api/sentiment/today', { timeout })
}

function getTodaySentimentWithRetry(options = {}) {
  const timeout = clampTimeout(options.timeout || HOME_FETCH_TIMEOUT_MS || HTTP_TIMEOUT_MS)
  const attempts = Math.max(1, Number(options.maxAttempts) || 2)

  const run = (idx, useHttpOnly) => {
    const opts = {
      ...options,
      timeout,
      httpOnly: useHttpOnly || options.httpOnly === true,
      skipFallback: useHttpOnly || options.skipFallback === true
    }
    return getTodaySentiment(opts).catch(err => {
      if (idx + 1 >= attempts) throw err
      if (isCacheWarmingError(err)) {
        return sleep(4000).then(() => run(idx + 1, false))
      }
      if (isTimeoutError(err) || isRetryableError(err)) {
        return sleep(800).then(() => run(idx + 1, true))
      }
      throw err
    })
  }
  return run(0, isDevtoolsEnv())
}

function getAdvice() {
  return request('/api/sentiment/advice')
}

function getHistory(days = 30, options = {}) {
  const timeout = clampTimeout(options.timeout || HTTP_TIMEOUT_MS)
  if (API_BASE && (options.httpOnly || HTTP_PREFER_DIRECT)) {
    return httpRequest(`/api/sentiment/history?days=${days}&tab=day`, { timeout })
  }
  return request(`/api/sentiment/history?days=${days}&tab=day`, { timeout })
}

function checkHealth() {
  return request('/api/health').catch(() => null)
}

function loginUser(payload, options = {}) {
  return request('/api/user/login', {
    method: 'POST',
    data: payload,
    timeout: options.timeout || 15000,
    skipFallback: options.skipFallback === true
  })
}

function registerSubscribe(code, type = 'sentiment_daily') {
  const opts = {
    method: 'POST',
    data: { code, type },
    timeout: 20000,
  }
  return request('/api/subscribe/register', opts).catch(err => {
    if (shouldUseCloudCall() && API_BASE && isRetryableError(err)) {
      return httpRequest('/api/subscribe/register', opts)
    }
    throw err
  })
}

function previewSubscribe(kind = 'sentiment_daily') {
  return request(`/api/subscribe/preview?kind=${kind}`)
}

function sendSubscribeTest(code, kind = 'sentiment_daily') {
  return request('/api/subscribe/send-test', {
    method: 'POST',
    data: { code, kind }
  })
}

module.exports = {
  request,
  uploadOcr,
  getTodaySentiment,
  getTodaySentimentWithRetry,
  getAdvice,
  getHistory,
  checkHealth,
  loginUser,
  registerSubscribe,
  previewSubscribe,
  sendSubscribeTest,
  ensureCloudInit,
  isDevtoolsEnv,
  shouldUseCloudCall,
  isTimeoutError,
  isRetryableError,
  isCacheWarmingError
}
