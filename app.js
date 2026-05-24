const { homeData } = require('./utils/data')

const { loadQuoteFont } = require('./utils/quoteFont')

const { ensureCloudInit, shouldUseCloudCall } = require('./utils/api')

const { initTheme } = require('./utils/uiTheme')

const { initUserProfile } = require('./utils/userProfile')

const { shouldRefreshHomeCache, warmHomeCacheFromStorage } = require('./utils/homeCache')

const { prefetchHome, shouldSkipHomeNetwork } = require('./utils/store')



App({

  globalData: {

    primaryColor: '#FF4D4F',

    riskLevel: 'steady',

    todayScore: homeData.score,

    todayAdvice: null,

    quoteFontReady: false,

    uiTheme: 'dark',

    homeSentimentCache: null,

    userProfile: null

  },



  prefetchHomeSentiment() {

    if (this._homePrefetching) return this._homePrefetchPromise

    this._homePrefetching = true

    this._homePrefetchPromise = prefetchHome().finally(() => {

      this._homePrefetching = false

    })

    return this._homePrefetchPromise

  },



  onLaunch() {

    const risk = wx.getStorageSync('riskLevel')

    if (risk) {

      this.globalData.riskLevel = risk

    }

    this.globalData.uiTheme = initTheme()
    initUserProfile()
    warmHomeCacheFromStorage()

    loadQuoteFont().then(ok => {
      this.globalData.quoteFontReady = ok
    }).catch(() => {})

    if (shouldUseCloudCall()) {
      ensureCloudInit().then(() => {
        if (shouldSkipHomeNetwork()) return
        this.prefetchHomeSentiment().catch(() => null)
      })
    } else if (!shouldSkipHomeNetwork()) {
      this.prefetchHomeSentiment().catch(() => null)
    }

  },



  onShow() {

    if (shouldSkipHomeNetwork()) return

    if (shouldRefreshHomeCache()) {

      this.prefetchHomeSentiment().catch(() => null)

    }

  },



  setTodaySentiment(score, advice) {

    this.globalData.todayScore = score

    this.globalData.todayAdvice = advice

  }

})

