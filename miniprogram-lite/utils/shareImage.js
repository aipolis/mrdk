function promptAlbumSetting(filePath) {
  return new Promise((resolve, reject) => {
    wx.showModal({
      title: '需要相册权限',
      content: '保存分享图需要访问相册，请在设置中开启',
      confirmText: '去设置',
      success: res => {
        if (!res.confirm) {
          reject(new Error('cancel'))
          return
        }
        wx.openSetting({
          success: ({ authSetting }) => {
            if (authSetting && authSetting['scope.writePhotosAlbum']) {
              wx.saveImageToPhotosAlbum({ filePath, success: resolve, fail: reject })
            } else {
              reject(new Error('auth deny'))
            }
          },
          fail: reject,
        })
      },
    })
  })
}

function savePosterToAlbum(filePath) {
  if (!filePath) return Promise.reject(new Error('empty poster'))
  return new Promise((resolve, reject) => {
    wx.getSetting({
      success: ({ authSetting }) => {
        const albumAuth = authSetting && authSetting['scope.writePhotosAlbum']
        const trySave = () => {
          wx.saveImageToPhotosAlbum({
            filePath,
            success: resolve,
            fail: err => {
              const msg = String((err && err.errMsg) || '')
              if (msg.includes('auth deny') || msg.includes('authorize')) {
                promptAlbumSetting(filePath).then(resolve).catch(reject)
              } else {
                reject(err || new Error('save fail'))
              }
            },
          })
        }
        if (albumAuth || albumAuth === undefined) trySave()
        else promptAlbumSetting(filePath).then(resolve).catch(reject)
      },
      fail: reject,
    })
  })
}

function forwardPosterImage(filePath) {
  if (!filePath) return Promise.reject(new Error('empty poster'))
  return new Promise((resolve, reject) => {
    if (wx.showShareImageMenu) {
      wx.showShareImageMenu({
        path: filePath,
        success: () => resolve(true),
        fail: err => {
          const msg = String((err && err.errMsg) || '')
          if (msg.includes('cancel')) resolve(false)
          else reject(err || new Error('forward fail'))
        },
      })
      return
    }
    reject(new Error('unsupported'))
  })
}

module.exports = { savePosterToAlbum, forwardPosterImage }
