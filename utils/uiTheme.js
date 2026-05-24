/** 界面主题：dark 黑底 / light 白底，本地缓存 */

const STORAGE_KEY = 'uiTheme'
const DEFAULT_THEME = 'dark'

const NAV = {
  dark: { frontColor: '#ffffff', backgroundColor: '#0a0e1a' },
  light: { frontColor: '#000000', backgroundColor: '#ffffff' }
}

const TAB = {
  dark: {
    color: '#6b7280',
    selectedColor: '#ff4d4f',
    backgroundColor: '#0f1424',
    borderStyle: 'white'
  },
  light: {
    color: '#9ca3af',
    selectedColor: '#ff4d4f',
    backgroundColor: '#ffffff',
    borderStyle: 'black'
  }
}

const PAGE_BG = {
  dark: '#0a0e1a',
  light: '#f3f4f6'
}

function normalizeTheme(theme) {
  return theme === 'light' ? 'light' : 'dark'
}

function getTheme() {
  try {
    const stored = wx.getStorageSync(STORAGE_KEY)
    if (stored) return normalizeTheme(stored)
  } catch (e) { /* ignore */ }
  const app = getApp()
  if (app && app.globalData && app.globalData.uiTheme) {
    return normalizeTheme(app.globalData.uiTheme)
  }
  return DEFAULT_THEME
}

function setTheme(theme) {
  const t = normalizeTheme(theme)
  try {
    wx.setStorageSync(STORAGE_KEY, t)
  } catch (e) { /* ignore */ }
  const app = getApp()
  if (app && app.globalData) app.globalData.uiTheme = t
  applyTheme(t)
  return t
}

function toggleTheme() {
  return setTheme(getTheme() === 'dark' ? 'light' : 'dark')
}

function applyTheme(theme) {
  const t = normalizeTheme(theme)
  const nav = NAV[t]
  const tab = TAB[t]
  const bg = PAGE_BG[t]

  wx.setBackgroundColor({
    backgroundColor: bg,
    backgroundColorTop: bg,
    backgroundColorBottom: bg
  })

  wx.setNavigationBarColor({
    frontColor: nav.frontColor,
    backgroundColor: nav.backgroundColor,
    animation: { duration: 200, timingFunc: 'easeIn' }
  })

  try {
    wx.setTabBarStyle({
      color: tab.color,
      selectedColor: tab.selectedColor,
      backgroundColor: tab.backgroundColor,
      borderStyle: tab.borderStyle
    })
  } catch (e) { /* 非 Tab 页 */ }

  const pages = getCurrentPages()
  pages.forEach(page => {
    if (page && page.setData && page.data && page.data.uiTheme !== t) {
      page.setData({ uiTheme: t })
    }
    if (page && typeof page.onUiThemeChange === 'function') {
      page.onUiThemeChange(t)
    }
  })

  return t
}

function initTheme() {
  const t = getTheme()
  applyTheme(t)
  return t
}

function getChartColors(theme) {
  const isLight = normalizeTheme(theme) === 'light'
  return {
    grid: isLight ? 'rgba(15, 23, 42, 0.08)' : 'rgba(255, 255, 255, 0.06)',
    textMuted: isLight ? '#9ca3af' : '#6b7280',
    line: '#ff4d4f',
    fill: isLight ? 'rgba(255, 77, 79, 0.1)' : 'rgba(255, 77, 79, 0.08)',
    pointInner: isLight ? '#ffffff' : '#141a2e',
    pointStroke: '#ff7875'
  }
}

function getGaugeTheme(theme) {
  const isLight = normalizeTheme(theme) === 'light'
  return {
    track: isLight ? '#e5e7eb' : '#232b3e',
    innerRing: isLight ? 'rgba(15, 23, 42, 0.06)' : 'rgba(255, 255, 255, 0.05)',
    tickActive: isLight ? 'rgba(15, 23, 42, 0.2)' : 'rgba(255,255,255,0.15)',
    tickIdle: isLight ? 'rgba(15, 23, 42, 0.08)' : 'rgba(255,255,255,0.05)',
    inactiveLow: isLight ? '#d1d5db' : '#3d4659',
    inactiveHigh: isLight ? '#e5e7eb' : '#2a3348'
  }
}

module.exports = {
  STORAGE_KEY,
  DEFAULT_THEME,
  getTheme,
  setTheme,
  toggleTheme,
  applyTheme,
  initTheme,
  getChartColors,
  getGaugeTheme
}
