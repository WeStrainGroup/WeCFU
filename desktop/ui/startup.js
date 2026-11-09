'use strict';
async function refresh() {
  try {
    const status = await window.__TAURI__.core.invoke('boot_status');
    document.body.dataset.phase = status.phase;
    document.getElementById('title').textContent = status.title;
    document.getElementById('message').textContent = status.message;
    const detail = document.getElementById('detail');
    detail.textContent = status.detail || '';
    detail.hidden = !status.detail;
  } catch (_) {
    document.body.dataset.phase = 'error';
    document.getElementById('title').textContent = 'Unable to start';
    document.getElementById('message').textContent = 'The desktop launcher is unavailable. Close this window and reopen WeCFU.';
  }
}
refresh();
setInterval(refresh, 250);
