export function initFooterContact() {
  document.querySelectorAll('.footer-contact-copy').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const text = btn.dataset.copy
      if (!text) return

      const copied = await copyText(text)
      if (copied) showCopied(btn)
    })
  })
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.setAttribute('readonly', '')
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    } catch {
      return false
    }
  }
}

function showCopied(btn) {
  btn.classList.add('is-copied')
  if (btn._originalTitle == null) btn._originalTitle = btn.title || '复制'
  btn.title = '已复制'
  clearTimeout(btn._copyTimer)
  btn._copyTimer = setTimeout(() => {
    btn.classList.remove('is-copied')
    btn.title = btn._originalTitle
  }, 2000)
}
