import { showToast } from "./dialog.js";

// 与旧版 setStatus 语义一致：写隐藏状态元素（兼容调试）+ 弹一条 toast。
export function setStatus(text) {
  const el = document.getElementById("global-status");
  if (el) el.textContent = text;
  if (text) showToast(text);
}
