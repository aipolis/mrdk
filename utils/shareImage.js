/**

 * 分享海报：下载小程序码、Canvas 生成、保存、转发

 */



const { API_BASE } = require('./config')
const { request, isDevtoolsEnv } = require('./api')

const { generateSharePoster } = require('./sharePoster')



const SHARE_SLOGAN = '不追求每天都有机会，而是帮你识别「不该出手」的日子'

const QRCODE_CACHE_KEY = 'share_qrcode_path_v1'

const QRCODE_FILE = `${wx.env.USER_DATA_PATH}/share_wxacode.png`



function getQrcodeUrl() {

  if (!API_BASE) return ''

  return `${API_BASE.replace(/\/$/, '')}/api/wxacode/share`

}



function writeQrcodeBase64(base64) {

  const fs = wx.getFileSystemManager()

  return new Promise((resolve, reject) => {

    fs.writeFile({

      filePath: QRCODE_FILE,

      data: base64,

      encoding: 'base64',

      success: () => {

        try {

          wx.setStorageSync(QRCODE_CACHE_KEY, QRCODE_FILE)

        } catch (e) {

          /* ignore */

        }

        resolve(QRCODE_FILE)

      },

      fail: reject

    })

  })

}



function fetchQrcodeViaApi() {

  return request('/api/wxacode/share-b64', { timeout: 20000 })

    .then(data => {

      if (!data || !data.base64) throw new Error('empty qrcode')

      return writeQrcodeBase64(data.base64)

    })

}



function downloadQrcode() {

  const cached = wx.getStorageSync(QRCODE_CACHE_KEY)

  if (cached) {

    return Promise.resolve(cached)

  }

  if (isDevtoolsEnv()) {
    return fetchQrcodeViaApi().catch(() => '/images/logo-192.png')
  }

  const url = getQrcodeUrl()

  if (url) {

    return new Promise((resolve, reject) => {

      wx.downloadFile({

        url,

        timeout: 20000,

        success: res => {

          if (res.statusCode === 200 && res.tempFilePath) {

            try {

              wx.setStorageSync(QRCODE_CACHE_KEY, res.tempFilePath)

            } catch (e) {

              /* ignore */

            }

            resolve(res.tempFilePath)

          } else {

            reject(new Error('download qrcode failed'))

          }

        },

        fail: reject

      })

    }).catch(() => fetchQrcodeViaApi().catch(() => '/images/logo-192.png'))

  }

  return fetchQrcodeViaApi().catch(() => '/images/logo-192.png')

}



function buildPosterData(pageData) {
  const display = Number(pageData.displayScore)
  const score = !Number.isNaN(display) && pageData.displayScore !== ''
    ? display
    : Number(pageData.score || 0)

  return {

    score,
    displayScore: score,

    levelLabel: pageData.levelLabel,

    levelClass: pageData.levelClass,

    positionDesc: pageData.positionDesc,

    dailyQuoteText: pageData.dailyQuoteText,

    dailyQuoteAuthor: pageData.dailyQuoteAuthor,

    generatedAt: pageData.generatedAt || '昨日 15:00 更新',

    indicatorSections: pageData.indicatorSections || [],

    slogan: SHARE_SLOGAN

  }

}



function promptAlbumSetting(filePath) {

  return new Promise((resolve, reject) => {

    wx.showModal({

      title: '需要相册权限',

      content: '请在设置中允许保存图片到相册',

      confirmText: '去设置',

      success: res => {

        if (!res.confirm) {

          reject(new Error('no album auth'))

          return

        }

        wx.openSetting({

          success: setting => {

            if (setting.authSetting && setting.authSetting['scope.writePhotosAlbum']) {

              wx.saveImageToPhotosAlbum({ filePath, success: resolve, fail: reject })

            } else {

              reject(new Error('no album auth'))

            }

          },

          fail: reject

        })

      },

      fail: reject

    })

  })

}



function savePosterToAlbum(filePath) {

  if (!filePath) {

    return Promise.reject(new Error('empty poster'))

  }

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

            }

          })

        }

        if (albumAuth || albumAuth === undefined) {

          trySave()

          return

        }

        promptAlbumSetting(filePath).then(resolve).catch(reject)

      },

      fail: reject

    })

  })

}



function forwardPosterImage(filePath) {

  if (!filePath) {

    return Promise.reject(new Error('empty poster'))

  }

  return new Promise((resolve, reject) => {

    if (wx.showShareImageMenu) {

      wx.showShareImageMenu({

        path: filePath,

        success: () => resolve(true),

        fail: err => {

          const msg = String((err && err.errMsg) || '')

          if (msg.includes('cancel')) {

            resolve(false)

            return

          }

          reject(err || new Error('share fail'))

        }

      })

      return

    }

    wx.previewImage({

      urls: [filePath],

      current: filePath,

      success: () => resolve(true),

      fail: reject

    })

  })

}



/** 拉取小程序码 + 离屏 Canvas 绘制，返回本地临时图片路径 */

function createSharePoster(pageData) {

  return downloadQrcode()

    .then(qrPath => generateSharePoster(buildPosterData(pageData), qrPath))

}



module.exports = {

  createSharePoster,

  savePosterToAlbum,

  forwardPosterImage,

  buildPosterData,

  SHARE_SLOGAN

}


