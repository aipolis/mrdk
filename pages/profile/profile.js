const { requestSubscribe } = require('../../utils/subscribe')
const uiThemeBehavior = require('../../behaviors/uiTheme')
const {
  getDisplayProfile,
  saveProfile,
  clearProfile,
  persistAvatar,
  syncUserToServer,
  syncPrefsFromApp,
  DEFAULT_AVATAR
} = require('../../utils/userProfile')

Page({
  behaviors: [uiThemeBehavior],

  data: {
    pushEnabled: false,
    loggedIn: false,
    avatarUrl: '',
    nickName: '',
    userId: null,
    openidHint: '',
    loginAvatarUrl: '',
    loginNickName: ''
  },

  onShow() {
    this.loadProfile()
    this.setData({
      pushEnabled: !!wx.getStorageSync('subscribe_sentimentDaily')
    })
  },

  loadProfile() {
    const profile = getDisplayProfile()
    if (profile.loggedIn) {
      this.showLoggedIn(profile)
      return
    }
    this.setData({
      loggedIn: false,
      avatarUrl: '',
      nickName: '',
      userId: null,
      openidHint: '',
      loginAvatarUrl: this.data.loginAvatarUrl || '',
      loginNickName: this.data.loginNickName || ''
    })
  },

  showLoggedIn(profile) {
    this.setData({
      loggedIn: true,
      avatarUrl: profile.avatarUrl || DEFAULT_AVATAR,
      nickName: profile.nickName || '',
      userId: profile.userId != null ? profile.userId : null,
      openidHint: profile.openidHint || '',
      loginAvatarUrl: '',
      loginNickName: ''
    })
  },

  readNickName() {
    return new Promise(resolve => {
      const cached = (this.data.loginNickName || '').trim()
      if (cached) {
        resolve(cached)
        return
      }
      wx.createSelectorQuery()
        .in(this)
        .select('#nickname-input')
        .fields({ properties: ['value'] })
        .exec(res => {
          const value = res && res[0] && res[0].value
          resolve((value || '').trim())
        })
    })
  },

  completeLogin(avatarUrl, nickName) {
    if (this.data.loggedIn || this._autoLogging) return
    this._autoLogging = true

    const profile = saveProfile({ avatarUrl, nickName })
    this.showLoggedIn(profile)

    syncUserToServer({ avatarUrl, nickName })
      .then(serverProfile => {
        if (serverProfile) {
          this.showLoggedIn(serverProfile)
          syncPrefsFromApp()
        }
      })
      .catch(() => {})
      .finally(() => {
        this._autoLogging = false
      })
  },

  tryAutoLogin() {
    if (this.data.loggedIn || this._autoLogging) return
    const avatarUrl = this.data.loginAvatarUrl
    if (!avatarUrl) return

    this.readNickName().then(nickName => {
      if (!nickName) return
      this.completeLogin(avatarUrl, nickName)
    })
  },

  onChooseAvatar(e) {
    const tempUrl = e.detail && e.detail.avatarUrl
    if (!tempUrl) return
    persistAvatar(tempUrl).then(saved => {
      this.setData({ loginAvatarUrl: saved || tempUrl }, () => {
        this.tryAutoLogin()
      })
    })
  },

  onNicknameInput(e) {
    const nick = (e.detail && e.detail.value) || ''
    this.setData({ loginNickName: nick })
    if ((nick || '').trim()) {
      clearTimeout(this._nickAutoLoginTimer)
      this._nickAutoLoginTimer = setTimeout(() => this.tryAutoLogin(), 200)
    }
  },

  onNicknameBlur(e) {
    this.setData({ loginNickName: ((e.detail && e.detail.value) || '').trim() }, () => {
      this.tryAutoLogin()
    })
  },

  onNicknameReview(e) {
    const detail = (e && e.detail) || {}
    if (detail.pass === false) {
      wx.showToast({ title: '昵称未通过审核，请换一个', icon: 'none' })
      return
    }
    const value = ((detail.value || this.data.loginNickName || '') + '').trim()
    if (!value) return
    this.setData({ loginNickName: value }, () => {
      this.tryAutoLogin()
    })
  },

  onLogout() {
    wx.showModal({
      title: '退出登录',
      content: '退出后仍保留你的主题等设置',
      success: res => {
        if (!res.confirm) return
        clearProfile()
        this.loadProfile()
      }
    })
  },

  onPushChange(e) {
    const on = e.detail.value
    if (!on) {
      wx.removeStorageSync('subscribe_sentimentDaily')
      this.setData({ pushEnabled: false })
      syncPrefsFromApp()
      if (this.data.loggedIn) {
        const { refreshUserSession } = require('../../utils/userProfile')
        refreshUserSession()
      }
      return
    }
    requestSubscribe('sentimentDaily').then(ok => {
      this.setData({ pushEnabled: !!ok })
      syncPrefsFromApp()
      if (ok && this.data.loggedIn) {
        const { refreshUserSession } = require('../../utils/userProfile')
        refreshUserSession()
      }
    })
  },

  goAbout() {
    wx.showModal({
      title: '关于明日当空',
      content: '不追求每天都有机会，而是帮你识别「不该出手」的日子',
      showCancel: false
    })
  },

  goDisclaimer() {
    wx.showModal({
      title: '免责声明',
      content: '本工具仅展示市场公开数据及个人复盘记录，不构成任何证券投资咨询或操作建议。用户须独立判断，盈亏自负。股市有风险，投资需谨慎。',
      showCancel: false
    })
  }
})
