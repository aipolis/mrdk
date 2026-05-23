import { fetchToday } from './api.js'
import { renderPosterToCanvas, posterFilename, posterToBlob } from './posterDraw.js'

const preview = document.getElementById('previewCanvas')
const statusBar = document.getElementById('statusBar')
const downloadBtn = document.getElementById('downloadBtn')
const refreshBtn = document.getElementById('refreshBtn')
const previewWrap = document.querySelector('.poster-preview-wrap')

let latestData = null

function setStatus(msg, type = '') {
  if (!statusBar) return
  statusBar.textContent = msg
  statusBar.className = type ? `status-bar ${type}` : 'status-bar'
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
      } catch (renderErr) {
        console.error(renderErr)
        previewWrap?.classList.remove('loading')
        setStatus(renderErr?.message || '海报绘制失败', 'err')
        if (downloadBtn) downloadBtn.disabled = true
      }
    })
  } catch (err) {
    console.error(err)
    previewWrap?.classList.remove('loading')
    setStatus(err?.message || '海报绘制失败', 'err')
    if (downloadBtn) downloadBtn.disabled = true
  }
}

async function downloadPoster() {
  if (!latestData) return
  if (downloadBtn) downloadBtn.disabled = true
  try {
    const blob = await posterToBlob(latestData)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = posterFilename(latestData)
    a.click()
    URL.revokeObjectURL(url)
    setStatus('图片已保存到下载文件夹', 'ok')
  } catch (err) {
    console.error(err)
    setStatus(err?.message || '下载失败', 'err')
  } finally {
    if (downloadBtn) downloadBtn.disabled = false
  }
}

refreshBtn?.addEventListener('click', loadAndDraw)
downloadBtn?.addEventListener('click', downloadPoster)
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
