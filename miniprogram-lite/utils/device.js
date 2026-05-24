function getPixelRatio() {
  try {
    return wx.getWindowInfo().pixelRatio || wx.getSystemInfoSync().pixelRatio || 2
  } catch (e) {
    return 2
  }
}

module.exports = { getPixelRatio }
