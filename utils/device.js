/** 设备信息与高 DPI Canvas 适配（进程内只读一次，避免重复监听 WindowInfoChanged） */

let _cachedWindowInfo = null
let _cachedDpr = null
let _cachedNavLayout = null

function getWindowInfoCached() {
  if (_cachedWindowInfo) return _cachedWindowInfo
  try {
    if (wx.getWindowInfo) {
      _cachedWindowInfo = wx.getWindowInfo()
    } else {
      _cachedWindowInfo = wx.getSystemInfoSync()
    }
  } catch (e) {
    _cachedWindowInfo = { pixelRatio: 2, statusBarHeight: 20, screenWidth: 375 }
  }
  return _cachedWindowInfo
}

function getPixelRatio() {
  if (_cachedDpr) return _cachedDpr
  const dpr = getWindowInfoCached().pixelRatio || 2
  _cachedDpr = Math.min(Math.max(Math.round(dpr), 2), 3)
  return _cachedDpr
}

/**
 * 自定义导航栏布局（避让右上角胶囊：··· 与关闭）
 * @returns {{ navCapSafeHeight: number, navSpacerHeight: number }}
 */
function getCustomNavLayout(forceRefresh) {
  if (_cachedNavLayout && !forceRefresh) {
    return _cachedNavLayout
  }
  const win = getWindowInfoCached()
  const statusBarHeight = win.statusBarHeight || 20
  const screenWidth = win.screenWidth || 375

  let menu = {
    top: statusBarHeight,
    bottom: statusBarHeight + 32,
    height: 32,
    left: screenWidth - 87,
  }
  try {
    const rect = wx.getMenuButtonBoundingClientRect()
    if (rect && rect.width > 0) {
      menu = rect
    }
  } catch (e) {
    /* ignore */
  }

  const capGap = 6
  const capSafe = Math.ceil(menu.bottom + capGap)
  const rowHeight = 40
  const spacerHeight = capSafe + rowHeight + 12

  _cachedNavLayout = {
    navCapSafeHeight: capSafe,
    navSpacerHeight: spacerHeight,
  }
  return _cachedNavLayout
}

/**
 * 绑定 2d canvas 为物理像素整数尺寸，避免发虚
 * @returns {{ width: number, height: number, dpr: number }}
 */
function setupCanvas2d(canvas, ctx, cssWidth, cssHeight) {
  const dpr = getPixelRatio()
  const width = Math.floor(cssWidth)
  const height = Math.floor(cssHeight)
  const pxW = Math.floor(width * dpr)
  const pxH = Math.floor(height * dpr)
  canvas.width = pxW
  canvas.height = pxH
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.scale(pxW / width, pxH / height)
  return { width, height, dpr }
}

module.exports = { getPixelRatio, setupCanvas2d, getCustomNavLayout }
