// "状态栏"文本：写进隐藏元素（兼容调试与旧行为）。
//
// ⚠️ 这里**不能顺带弹 toast**：导入 Mod 时它是**按分块（每 1MB）调一次**的，
// 带 toast 就会连弹上百条（用户 2026-10-03 反馈"拖入 zip 会弹出来一堆动态"）。
// 需要弹出提示的地方，请直接调 dialog.js 的 showToast / showAlert。
export function setStatus(text) {
  const el = document.getElementById("global-status");
  if (el) el.textContent = text;
}
