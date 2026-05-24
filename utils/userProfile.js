/** 用户登录态与偏好设置（本地持久化 + 服务端 openid 同步） */

const { loginUser } = require('./api')

const STORAGE_KEY = 'userProfile_v1'
const PREFS_KEY = 'userPrefs_v1'
const DEFAULT_AVATAR = '/images/logo-192.png'
const DEFAULT_NICKNAME = '微信用户'

function readStorageProfile() {
  try {
    const stored = wx.getStorageSync(STORAGE_KEY)
    if (stored && typeof stored === 'object') return stored
  } catch (e) {
    /* ignore */
  }
  return null
}

function readAppProfile() {
  try {
    const app = getApp()
    const stored = app && app.globalData && app.globalData.userProfile
    if (stored && typeof stored === 'object') return stored
  } catch (e) {
    /* ignore */
  }
  return null
}

function isLoggedInRecord(raw) {
  if (!raw || typeof raw !== 'object') return false
  if (raw.loggedIn === true || raw.loggedIn === 1 || raw.loggedIn === 'true') return true
  return raw.userId != null && raw.userId !== ''
}

function normalizeProfile(raw) {
  if (!isLoggedInRecord(raw)) return null
  return {
    ...raw,
    loggedIn: true,
    avatarUrl: raw.avatarUrl || DEFAULT_AVATAR,
    nickName: (raw.nickName || DEFAULT_NICKNAME).trim() || DEFAULT_NICKNAME,
    userId: raw.userId != null && raw.userId !== '' ? raw.userId : null,
    openidHint: raw.openidHint || ''
  }
}

function persistProfileRecord(data) {
  try {
    const app = getApp()
    if (app && app.globalData) app.globalData.userProfile = data
  } catch (e) {
    /* ignore */
  }
  try {
    wx.setStorageSync(STORAGE_KEY, data)
  } catch (e) {
    /* ignore */
  }
}

function getProfile() {
  const storageNorm = normalizeProfile(readStorageProfile())
  const appNorm = normalizeProfile(readAppProfile())
  if (storageNorm && appNorm) {
    const sTime = storageNorm.updatedAt || 0
    const aTime = appNorm.updatedAt || 0
    return sTime >= aTime ? storageNorm : appNorm
  }
  const data = storageNorm || appNorm
  if (data && readStorageProfile() && !readStorageProfile().loggedIn) {
    persistProfileRecord(data)
  }
  return data
}

function saveProfile(profile) {
  const prev = getProfile() || {}
  const data = {
    avatarUrl: profile.avatarUrl || prev.avatarUrl || DEFAULT_AVATAR,
    nickName: (profile.nickName || prev.nickName || DEFAULT_NICKNAME).trim() || DEFAULT_NICKNAME,
    loggedIn: true,
    userId: profile.userId != null ? profile.userId : prev.userId,
    openidHint: profile.openidHint || prev.openidHint || '',
    updatedAt: Date.now()
  }
  persistProfileRecord(data)
  syncPrefsFromApp()
  return data
}

function clearProfile() {
  try {
    wx.removeStorageSync(STORAGE_KEY)
  } catch (e) {
    /* ignore */
  }
  try {
    const app = getApp()
    if (app && app.globalData) app.globalData.userProfile = null
  } catch (e) {
    /* ignore */
  }
}

function isLoggedIn() {
  return !!getProfile()
}

function getDisplayProfile() {
  const p = getProfile()
  if (p) {
    return {
      loggedIn: true,
      avatarUrl: p.avatarUrl || DEFAULT_AVATAR,
      nickName: p.nickName || DEFAULT_NICKNAME,
      userId: p.userId,
      openidHint: p.openidHint || ''
    }
  }
  return {
    loggedIn: false,
    avatarUrl: '',
    nickName: '',
    userId: null,
    openidHint: ''
  }
}

function getPrefs() {
  try {
    return wx.getStorageSync(PREFS_KEY) || {}
  } catch (e) {
    return {}
  }
}

function savePrefs(prefs) {
  const merged = { ...getPrefs(), ...prefs, updatedAt: Date.now() }
  try {
    wx.setStorageSync(PREFS_KEY, merged)
  } catch (e) {
    /* ignore */
  }
  return merged
}

function syncPrefsFromApp() {
  const uiTheme = require('./uiTheme')
  let pushSentiment = false
  try {
    pushSentiment = !!wx.getStorageSync('subscribe_sentimentDaily')
  } catch (e) {
    /* ignore */
  }
  return savePrefs({
    uiTheme: uiTheme.getTheme(),
    pushSentiment
  })
}

function applyStoredPrefs() {
  const prefs = getPrefs()
  if (prefs.uiTheme) {
    const uiTheme = require('./uiTheme')
    uiTheme.setTheme(prefs.uiTheme)
  }
  return prefs
}

function buildLoginPayload(code, profile) {
  const prefs = syncPrefsFromApp()
  return {
    code,
    nickName: profile.nickName || DEFAULT_NICKNAME,
    avatarUrl: profile.avatarUrl || DEFAULT_AVATAR,
    uiTheme: prefs.uiTheme || '',
    pushSentiment: !!prefs.pushSentiment
  }
}

function syncUserToServer(profile, options = {}) {
  const { silent = false, timeout = 12000 } = options
  return wxLogin().then(code => {
    if (!code) {
      if (silent) return null
      return Promise.reject(new Error('wx.login 失败'))
    }
    return loginUser(buildLoginPayload(code, profile), { timeout })
  }).then(data => {
    if (!data) return null
    return saveProfile({
      avatarUrl: data.avatarUrl || profile.avatarUrl,
      nickName: data.nickName || profile.nickName,
      userId: data.userId,
      openidHint: data.openidHint
    })
  }).catch(err => {
    if (!silent) throw err
    return null
  })
}

function refreshUserSession() {
  const profile = getProfile()
  if (!profile || !profile.loggedIn) return Promise.resolve(null)
  return syncUserToServer(profile, { silent: true })
}

function initUserProfile() {
  const profile = getProfile()
  try {
    const app = getApp()
    if (app && app.globalData) {
      app.globalData.userProfile = profile
    }
  } catch (e) {
    /* ignore */
  }
  applyStoredPrefs()
  if (profile && profile.loggedIn) {
    setTimeout(() => {
      refreshUserSession().catch(() => {})
    }, 8000)
  }
  return profile
}

function persistAvatar(tempPath) {
  return new Promise(resolve => {
    if (!tempPath) {
      resolve('')
      return
    }
    if (!tempPath.startsWith('wxfile://') && !tempPath.startsWith('http')) {
      resolve(tempPath)
      return
    }
    try {
      const fs = wx.getFileSystemManager()
      fs.saveFile({
        tempFilePath: tempPath,
        success: res => resolve(res.savedFilePath || tempPath),
        fail: () => resolve(tempPath)
      })
    } catch (e) {
      resolve(tempPath)
    }
  })
}

function wxLogin() {
  return new Promise(resolve => {
    wx.login({
      success: res => resolve(res.code || ''),
      fail: () => resolve('')
    })
  })
}

module.exports = {
  STORAGE_KEY,
  PREFS_KEY,
  DEFAULT_AVATAR,
  DEFAULT_NICKNAME,
  getProfile,
  saveProfile,
  clearProfile,
  isLoggedIn,
  getDisplayProfile,
  getPrefs,
  savePrefs,
  syncPrefsFromApp,
  applyStoredPrefs,
  syncUserToServer,
  refreshUserSession,
  initUserProfile,
  persistAvatar,
  wxLogin
}
