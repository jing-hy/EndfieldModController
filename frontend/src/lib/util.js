// 工具函数：**照抄旧 app.js 的实现**（行为必须一致，别"顺手优化"）。
export function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

export function humanSize(bytes) {
  const n = Number(bytes) || 0;
  if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(0) + " KB";
  return n + " B";
}

export function fmtTime(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

// 站点/网址可点直接打开（用户 2026-10-01：「程序内所有给网址做了打开键的，全部去掉，
// 点击网址就可以直接打开了」）—— 点击由全局委托交给后端 open_external。
export function openExternal(url) {
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.open_external(url);
  }
}
