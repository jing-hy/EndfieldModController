// 与后端的唯一桥接点（旧 app.js 里 pywebview 的出现只有这几处，迁移时全部收敛到这里）。
//
// ⚠️ 行为必须与旧版一致：
//   * 桥没就绪 → 抛错，由后端 boot 重试逻辑兜底（pywebviewready / DOMContentLoaded 两道）；
//   * 调用失败 → **弹窗告知 + 原样抛出**（旧版如此，调用方依赖这个行为做错误分支）；
//   * 前端异常 → 上报后端日志（log_frontend_error）。
const READY_TIMEOUT_MS = 15000;

export function bridgeReady() {
  return !!(window.pywebview && window.pywebview.api);
}

export async function waitForBridge(timeout = READY_TIMEOUT_MS) {
  if (bridgeReady()) return true;
  const started = Date.now();
  while (Date.now() - started < timeout) {
    await new Promise((r) => setTimeout(r, 100));
    if (bridgeReady()) return true;
  }
  return false;
}

export async function call(method, ...args) {
  if (!bridgeReady()) throw new Error("PyWebview API is not ready");
  try {
    return await window.pywebview.api[method](...args);
  } catch (err) {
    const message = err && err.message ? err.message : String(err);
    // 延迟 import 避免循环依赖（dialog 里也可能用到 call）
    const { showAlert } = await import("./dialog.js");
    await showAlert(`${method} failed:\n${message}`);
    throw err;
  }
}

export function reportFrontendError(kind, msg) {
  try {
    if (bridgeReady()) window.pywebview.api.log_frontend_error(`${kind}: ${msg}`);
  } catch (e) {
    /* 上报失败不能再抛，否则递归 */
  }
}
