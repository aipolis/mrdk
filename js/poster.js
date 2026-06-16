import { fetchToday } from './api.js?v=20260609c'
import { renderPosterToCanvas, posterFilename, posterToBlob, isAlertModeAvailable } from './posterDraw.js?v=20260617e'

const preview = document.getElementById('previewCanvas')
const statusBar = document.getElementById('statusBar')
const downloadBtn = document.getElementById('downloadBtn')
const shareBtn = document.getElementById('shareBtn')

const previewWrap = document.querySelector('.poster-preview-wrap')
const imageModal = document.getElementById('imageModal')
const modalImage = document.getElementById('modalImage')
const closeModal = document.getElementById('closeModal')

const modeButtons = Array.from(document.querySelectorAll('.poster-mode-btn'))
const alertBadge = document.getElementById('alertBadge')

const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent)

let latestData = null
let currentMode = 'full'
let modalBlobUrl = null
let _blobCache = null   // 预生成的 blob
let _blobPending = null // 生成中的 Promise

function setStatus(msg, type = '') {
  if (!statusBar) return
  statusBar.textContent = msg
  statusBar.className = type ? `status-bar ${type}` : 'status-bar'
}

function showImageModal(blob) {
  if (modalBlobUrl) URL.revokeObjectURL(modalBlobUrl)
  modalBlobUrl = URL.createObjectURL(blob)
  if (modalImage) modalImage.src = modalBlobUrl
  if (imageModal) imageModal.style.display = 'flex'
}

closeModal?.addEventListener('click', () => {
  if (imageModal) imageModal.style.display = 'none'
})

async function tryNativeShare(blob, filename) {
  const file = new File([blob], filename, { type: 'image/jpeg' })
  if (!navigator.canShare || !navigator.canShare({ files: [file] })) return false
  await navigator.share({ files: [file], title: '明日当空 · 市场情绪' })
  return true
}

function syncModeUI() {
  const alertAvailable = isAlertModeAvailable(latestData)
  // 已经处于预警版（例如 URL 强制 / 龙空触发）时，按钮始终可点；否则只在数据触发时启用
  const alertClickable = alertAvailable || currentMode === 'alert'
  modeButtons.forEach((btn) => {
    const mode = btn.dataset.mode
    const isActive = mode === currentMode
    btn.classList.toggle('is-active', isActive)
    btn.setAttribute('aria-selected', isActive ? 'true' : 'false')
    if (mode === 'alert') btn.disabled = !alertClickable
  })
  if (alertBadge) alertBadge.hidden = !alertAvailable
}

function renderCurrentMode() {
  if (!latestData || !preview) return
  renderPosterToCanvas(latestData, preview, { mode: currentMode })
  // 切换后旧缓存失效；后台重新预生成对应模式的 blob
  _blobCache = null
  _blobPending = posterToBlob(latestData, { mode: currentMode })
  _blobPending.then((b) => { _blobCache = b }).catch(() => {})
}

async function loadAndDraw() {
  if (!preview) {
    setStatus('页面元素加载失败，请刷新重试', 'err')
    return
  }
  setStatus('正在加载今日数据…')
  if (downloadBtn) downloadBtn.disabled = true
  previewWrap?.classList.add('loading')

  try {
    const data = await fetchToday()
    latestData = data
  } catch (err) {
    previewWrap?.classList.remove('loading')
    setStatus(err?.message || '加载失败，请稍后重试', 'err')
    if (downloadBtn) downloadBtn.disabled = true
    if (shareBtn) shareBtn.disabled = true
    return
  }

  // 数据到手后决定初始模式：
  //  1. URL 参数 ?mode=alert|full 强制指定（便于测试 / 内容创作截图）
  //  2. 否则触发龙空时自动用预警版
  const urlMode = new URLSearchParams(location.search).get('mode')
  if (urlMode === 'alert' || urlMode === 'full') {
    currentMode = urlMode
  } else {
    currentMode = isAlertModeAvailable(latestData) ? 'alert' : 'full'
  }
  syncModeUI()

  try {
    requestAnimationFrame(() => {
      try {
        renderCurrentMode()
        previewWrap?.classList.remove('loading')
        const score = latestData.displayScore != null ? latestData.displayScore : latestData.score
        const tag = currentMode === 'alert' ? '龙空预警版' : '完整版'
        setStatus(`已生成 · ${tag} · 情绪分 ${score}`, 'ok')
        if (downloadBtn) downloadBtn.disabled = false
        if (shareBtn) shareBtn.disabled = false
      } catch (renderErr) {
        console.error(renderErr)
        previewWrap?.classList.remove('loading')
        setStatus(renderErr?.message || '海报绘制失败', 'err')
        if (downloadBtn) downloadBtn.disabled = true
        if (shareBtn) shareBtn.disabled = true
      }
    })
  } catch (err) {
    console.error(err)
    previewWrap?.classList.remove('loading')
    setStatus(err?.message || '海报绘制失败', 'err')
    if (downloadBtn) downloadBtn.disabled = true
  }
}

function getBlob() {
  return _blobCache
    ? Promise.resolve(_blobCache)
    : (_blobPending || posterToBlob(latestData, { mode: currentMode }))
}

async function downloadPoster() {
  if (!latestData || downloadBtn?.disabled) return
  if (downloadBtn) downloadBtn.disabled = true
  try {
    const blob = await getBlob()
    const filename = posterFilename(latestData, currentMode)
    if (isMobile) {
      const shared = await tryNativeShare(blob, filename).catch(() => false)
      if (shared) {
        setStatus('已打开分享', 'ok')
      } else {
        showImageModal(blob)
        setStatus('长按图片可保存到相册', '')
      }
    } else {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
      setStatus('图片已保存到下载文件夹', 'ok')
    }
  } catch (err) {
    if (err?.name !== 'AbortError') {
      console.error(err)
      setStatus(err?.message || '下载失败', 'err')
    }
  } finally {
    if (downloadBtn) downloadBtn.disabled = false
  }
}

async function sharePoster() {
  if (!latestData || shareBtn?.disabled) return
  if (shareBtn) shareBtn.disabled = true
  try {
    const blob = await getBlob()
    const filename = posterFilename(latestData, currentMode)
    const shared = await tryNativeShare(blob, filename).catch(() => false)
    if (shared) {
      setStatus('已打开分享', 'ok')
    } else {
      showImageModal(blob)
      setStatus('长按图片进行转发', '')
    }
  } catch (err) {
    if (err?.name !== 'AbortError') {
      console.error(err)
      setStatus(err?.message || '转发失败', 'err')
    }
  } finally {
    if (shareBtn) shareBtn.disabled = false
  }
}


downloadBtn?.addEventListener('click', downloadPoster)
shareBtn?.addEventListener('click', sharePoster)

modeButtons.forEach((btn) => {
  btn.addEventListener('click', () => {
    const next = btn.dataset.mode
    if (!next || btn.disabled || next === currentMode) return
    currentMode = next
    syncModeUI()
    if (!latestData) return
    try {
      renderCurrentMode()
      const score = latestData.displayScore != null ? latestData.displayScore : latestData.score
      const tag = currentMode === 'alert' ? '龙空预警版' : '完整版'
      setStatus(`已切换 · ${tag} · 情绪分 ${score}`, 'ok')
    } catch (err) {
      console.error(err)
      setStatus(err?.message || '海报绘制失败', 'err')
    }
  })
})

window.addEventListener('resize', () => {
  if (latestData && preview) {
    try {
      renderPosterToCanvas(latestData, preview, { mode: currentMode })
    } catch (err) {
      console.error(err)
    }
  }
})

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', loadAndDraw)
} else {
  loadAndDraw()
}
