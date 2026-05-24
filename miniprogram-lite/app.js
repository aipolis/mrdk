const { ensureCloudInit } = require('./utils/api')
const { USE_CLOUD_CALL, CLOUD_ENV } = require('./utils/config')

App({
  globalData: {
    userProfile: null,
  },

  onLaunch() {
    if (USE_CLOUD_CALL && CLOUD_ENV) {
      ensureCloudInit().catch(() => {})
    }
  },
})
