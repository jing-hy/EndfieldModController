// 全局 Toast + 命令式弹窗（保持旧 app.js 的 API 与语义，调用方一字不改）。
import { reactive } from "vue";

export const uiState = reactive({
  toasts: [],           // { id, text }
  dialog: null,         // { title, message, okText, cancelText, showCancel, link, extraButtons }
});

let toastSeq = 0;
// 按文案猜语气（评审：状态只靠颜色，看不出成功/警告/失败）。
// 调用方也可以显式传 tone，覆盖推断。
function inferTone(text) {
  const s = String(text);
  if (/失败|错误|无法|不存在|不能|取消/.test(s)) return "danger";
  if (/不确定|请选择|注意|需要|缺失/.test(s)) return "warn";
  if (/^已|完成|成功|就位/.test(s)) return "success";
  return "info";
}

// 进度提示：同一个 key 只占一条 toast，后续更新文本而不是再弹一条 ——
// 用于"上传中 12%…13%…"这类高频更新（否则会刷屏）。
const progressToasts = new Map();

export function showProgressToast(key, text) {
  if (!key) return;
  const existing = progressToasts.get(key);
  if (existing) {
    const found = uiState.toasts.find((t) => t.id === existing);
    if (found) {
      found.text = text;
      return;
    }
  }
  const id = ++toastSeq;
  progressToasts.set(key, id);
  uiState.toasts.push({ id, text, tone: "info", sticky: true });
}

export function hideProgressToast(key) {
  const id = progressToasts.get(key);
  if (!id) return;
  progressToasts.delete(key);
  const i = uiState.toasts.findIndex((t) => t.id === id);
  if (i >= 0) uiState.toasts.splice(i, 1);
}

export function showToast(text, tone) {
  if (!text) return;
  const id = ++toastSeq;
  uiState.toasts.push({ id, text, tone: tone || inferTone(text) });
  setTimeout(() => {
    const i = uiState.toasts.findIndex((t) => t.id === id);
    if (i >= 0) uiState.toasts.splice(i, 1);
  }, 2600);
}

// 旧版签名：showModalDialog({ title, message, okText, cancelText, showCancel, link, extraButtons })
// 返回 Promise<boolean>（点主按钮 = true）。正文用 textContent 渲染（**不允许写 markdown**）。
//
// `focusCancel`（2026-10-03 加）：**破坏性动作默认把焦点放在安全项（取消）上** —— 用户定的
// 交互准则之一（「破坏性动作写清后果、默认聚焦安全项」）。不传则维持旧行为（聚焦主按钮）。
export function showModalDialog({
  title, message, okText = "确定", cancelText = "取消",
  showCancel = true, link = null, extraButtons = [], focusCancel = false,
}) {
  return new Promise((resolve) => {
    uiState.dialog = {
      title, message, okText, cancelText, showCancel, link, extraButtons, focusCancel,
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
