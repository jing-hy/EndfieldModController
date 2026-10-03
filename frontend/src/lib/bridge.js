// 与后端的唯一桥接点（旧 app.js 里 pywebview 的出现只有这几处，迁移时全部收敛到这里）。
//
// ⚠️ 行为必须与旧版一致：
//   * 桥没就绪 → 抛错，由后端 boot 重试逻辑兜底（pywebviewready / DOMContentLoaded 两道）；
//   * 调用失败 → **弹窗告知 + 原样抛出**（旧版如此，调用方依赖这个行为做错误分支）；
//   * 前端异常 → 上报后端日志（log_frontend_error）。
//
// ⚠️⚠️ **2026-10-03 修「ui_ready failed: window.pywebview.api[e] is not a function」**：
// pywebview 的 `window.pywebview.api` 对象**先出现，方法是随后一个个注入的** ——
// 原来的 `bridgeReady()` 只判断 `window.pywebview.api` **存在**，于是 boot 最开始那次
// `call("ui_ready")` 会撞上"api 在、ui_ready 还没挂上"的窗口期，抛
// `api[e] is not a function`（`e` 是打包压缩后的变量名），界面上弹一个红框 ——
// 用户截图反馈的就是这条。
//
// 现在改为**按方法名判断**：`bridgeReady(method)` 要求那个方法**确实是个函数**；
// `waitForBridge(method)` 一直等到它出现（最多 15 秒）。`call()` 自己也走这条检查，
// 于是"桥就绪"的判据从"对象在不在"精确到"我要调的这个方法在不在"。
const READY_TIMEOUT_MS = 15000;

/**
 * 桥是否就绪。
 * @param {string} [method] 需要调用的后端方法名；给了就要求它**已经是个函数**。
 */
export function bridgeReady(method) {
  const api = window.pywebview && window.pywebview.api;
  if (!api) return false;
  if (!method) return true;
  return typeof api[method] === "function";
}

export async function waitForBridge(timeout = READY_TIMEOUT_MS, method) {
  if (bridgeReady(method)) return true;
  const started = Date.now();
  while (Date.now() - started < timeout) {
    await new Promise((r) => setTimeout(r, 100));
    if (bridgeReady(method)) return true;
  }
  return false;
}

export async function call(method, ...args) {
  // 等**这个具体方法**出现（最多 15 秒）—— 不再只看 api 对象在不在
  if (!bridgeReady(method)) {
    const ok = await waitForBridge(READY_TIMEOUT_MS, method);
    if (!ok) throw new Error(`PyWebview API is not ready（缺方法 ${method}）`);
  }
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
    if (bridgeReady("log_frontend_error")) {
      window.pywebview.api.log_frontend_error(`${kind}: ${msg}`);
    }
  } catch (e) {
    /* 上报失败不能再抛，否则递归 */
  }
}
