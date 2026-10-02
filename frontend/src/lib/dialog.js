// 全局 Toast + 命令式弹窗（保持旧 app.js 的 API 与语义，调用方一字不改）。
import { reactive } from "vue";

export const uiState = reactive({
  toasts: [],           // { id, text }
  dialog: null,         // { title, message, okText, cancelText, showCancel, link, extraButtons }
});

let toastSeq = 0;
export function showToast(text) {
  if (!text) return;
  const id = ++toastSeq;
  uiState.toasts.push({ id, text });
  setTimeout(() => {
    const i = uiState.toasts.findIndex((t) => t.id === id);
    if (i >= 0) uiState.toasts.splice(i, 1);
  }, 2600);
}

// 旧版签名：showModalDialog({ title, message, okText, cancelText, showCancel, link, extraButtons })
// 返回 Promise<boolean>（点主按钮 = true）。正文用 textContent 渲染（**不允许写 markdown**）。
export function showModalDialog({
  title, message, okText = "确定", cancelText = "取消",
  showCancel = true, link = null, extraButtons = [],
}) {
  return new Promise((resolve) => {
    uiState.dialog = {
      title, message, okText, cancelText, showCancel, link, extraButtons,
      _resolve: resolve,
    };
  });
}

export function resolveDialog(value) {
  const d = uiState.dialog;
  uiState.dialog = null;
  if (d && d._resolve) d._resolve(value);
}

export function showAlert(title, message) {
  return showModalDialog({ title, message, okText: "知道了", showCancel: false });
}

export function showConfirm(title, message, okText = "确定", cancelText = "取消") {
  return showModalDialog({ title, message, okText, cancelText });
}

export function showError(title, message) {
  return showAlert(title, message);
}
