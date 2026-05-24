const uiTheme = require('../utils/uiTheme')

module.exports = Behavior({
  data: {
    uiTheme: 'dark'
  },

  lifetimes: {
    attached() {
      this.syncUiTheme(false)
    }
  },

  pageLifetimes: {
    show() {
      this.syncUiTheme(false)
    }
  },

  methods: {
    syncUiTheme(applyBar) {
      const theme = uiTheme.getTheme()
      if (this.data.uiTheme !== theme) {
        this.setData({ uiTheme: theme })
      }
      if (applyBar) uiTheme.applyTheme(theme)
      return theme
    },

    onToggleTheme() {
      const theme = uiTheme.toggleTheme()
      this.setData({ uiTheme: theme })
      try {
        const userProfile = require('../utils/userProfile')
        userProfile.syncPrefsFromApp()
        userProfile.refreshUserSession()
      } catch (e) {
        /* ignore */
      }
      if (typeof this.onUiThemeChange === 'function') {
        this.onUiThemeChange(theme)
      }
    }
  }
})
