/**
 * 语录专用字体（仅 .quote-hand 使用）
 *
 * 三选一：wenkai 霞鹜文楷 | zcool 站酷快乐体 | smiley 得意黑
 * 优先本地子集 TTF，失败时尝试 CDN 全量（需在公众平台配置 downloadFile 合法域名）
 */

const { QUOTE_FONT } = require('./config')

const FONT_FAMILY = 'MRQuoteFont'

const FONT_PRESETS = {
  wenkai: {
    id: 'wenkai',
    label: '霞鹜文楷',
    local: '/assets/fonts/quote-wenkai-subset.ttf',
    cdn: 'https://cdn.jsdelivr.net/gh/lxgw/LxgwWenKai@v1.501/LXGWWenKai-Regular.ttf'
  },
  zcool: {
    id: 'zcool',
    label: '站酷快乐体',
    local: '/assets/fonts/quote-zcool-subset.ttf',
    cdn: 'https://cdn.jsdelivr.net/gh/googlefonts/zcool-kuaile@main/fonts/ttf/ZCOOLKuaiLe-Regular.ttf'
  },
  smiley: {
    id: 'smiley',
    label: '得意黑',
    local: '/assets/fonts/quote-smiley-subset.ttf',
    cdn: ''
  }
}

/** 禁用 CDN 全量字体兜底（19MB 会触发 timeout）；仅使用本地子集 */
const USE_FONT_CDN_FALLBACK = false

const QUOTE_EXTRA_CHARS = '与君共勉。、「」0123456789——'

function getActivePreset() {
  const key = FONT_PRESETS[QUOTE_FONT] ? QUOTE_FONT : 'wenkai'
  return FONT_PRESETS[key]
}

function getQuoteCharset(quotes) {
  const list = quotes || []
  const text = list.map(q => {
    if (typeof q === 'string') return q
    return String(q.text || '') + String(q.author || '')
  }).join('') + QUOTE_EXTRA_CHARS
  return Array.from(new Set(text.split(''))).join('')
}

function loadFromSource(source) {
  return new Promise((resolve, reject) => {
    if (typeof wx === 'undefined' || !wx.loadFontFace) {
      resolve(false)
      return
    }
    let settled = false
    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      resolve(false)
    }, 8000)
    wx.loadFontFace({
      family: FONT_FAMILY,
      source,
      global: true,
      desc: {
        style: 'normal',
        weight: 'normal'
      },
      success: () => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        resolve(true)
      },
      fail: err => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        reject(err || new Error('loadFontFace failed'))
      }
    })
  })
}

function loadQuoteFont() {
  const preset = getActivePreset()
  const localSource = `url("${preset.local}")`

  return loadFromSource(localSource)
    .then(ok => {
      if (ok || !USE_FONT_CDN_FALLBACK || !preset.cdn) return ok
      return loadFromSource(`url("${preset.cdn}")`)
    })
    .catch(() => false)
}

module.exports = {
  FONT_FAMILY,
  FONT_PRESETS,
  QUOTE_FONT: getActivePreset().id,
  QUOTE_EXTRA_CHARS,
  getActivePreset,
  getQuoteCharset,
  loadQuoteFont
}
