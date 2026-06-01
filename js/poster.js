import { fetchToday } from './api.js'
import { renderPosterToCanvas, posterFilename, posterToBlob } from './posterDraw.js?v=20260531a'

const preview = document.getElementById('previewCanvas')
const statusBar = document.getElementById('statusBar')
const downloadBtn = document.getElementById('downloadBtn')
const shareBtn = document.getElementById('shareBtn')

const previewWrap = document.querySelector('.poster-preview-wrap')
const imageModal = document.getElementById('imageModal')
const modalImage = document.getElementById('modalImage')
const closeModal = document.getElementById('closeModal')

const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent)

let latestData = null
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

  try {
    requestAnimationFrame(() => {
      try {
        renderPosterToCanvas(latestData, preview)
        previewWrap?.classList.remove('loading')
        const score = latestData.displayScore != null ? latestData.displayScore : latestData.score
        setStatus(`已生成 · 情绪分 ${score} · 可下载 PNG`, 'ok')
        if (downloadBtn) downloadBtn.disabled = false
        if (shareBtn) shareBtn.disabled = false
        // 预览完成后立即后台生成 blob，用户点分享时直接取缓存
        _blobCache = null
        _blobPending = posterToBlob(latestData)
        _blobPending.then((b) => { _blobCache = b }).catch(() => {})
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
  return _blobCache ? Promise.resolve(_blobCache) : (_blobPending || posterToBlob(latestData))
}

async function downloadPoster() {
  if (!latestData || downloadBtn?.disabled) return
  if (downloadBtn) downloadBtn.disabled = true
  try {
    const blob = await getBlob()
    const filename = posterFilename(latestData)
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
    const filename = posterFilename(latestData)
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
window.addEventListener('resize', () => {
  if (latestData && preview) {
    try {
      renderPosterToCanvas(latestData, preview)
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
