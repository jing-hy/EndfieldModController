// 「缺 VC++ 运行库 → 问要不要现在装」的公共弹窗（依赖页 / 启动页共用这一份）。
//
// 为什么单拎出来：后端 `runtime_deps.ensure_all` 会在结果里补一条 `VC++ 运行库`
// （status = `needs_install` ⇒ 缺了），启动页则用 `vc_runtime_status()` 主动查一次。
// 两处的文案与按钮语义必须一致 —— 用户要求：「**弹窗可以选安装或跳过，但是建议安装**」。
import { call } from "./bridge.js";
import { showAlert, showModalDialog, showProgressToast, hideProgressToast } from "./dialog.js";

const PROGRESS_KEY = "vc-runtime";

/** 后端 `ensure_all` 的结果里有没有「缺 VC++ 运行库」这一条。 */
export function needsVcRuntime(results) {
  return (Array.isArray(results) ? results : []).some(
    (item) => item && String(item.key || "").includes("VC++")
      && String(item.status) === "needs_install",
  );
}

/** 弹一次「安装（推荐）/ 跳过」；返回 `{ installed, skipped }`。 */
export async function promptVcRuntimeInstall() {
  const ok = await showModalDialog({
    title: "缺少 VC++ 运行库 —— 建议安装",
    message: [
      "ReShade 的插件（DLSS5 喂帧组件）依赖 VC++ 运行库，缺了它这些功能起不来。",
      "",
      "现在装的话：从**微软官方**下载约 24 MB 并静默安装（来源 aka.ms，国内可直连），",
      "装完会把版本号报给你。跳过也能照常启动，只是那些功能可能仍然不工作。",
    ].join("\n"),
    okText: "安装（推荐）", cancelText: "跳过",
    // ⚠️ 焦点给**主按钮**：这里是"推荐装"，与"破坏性动作默认聚焦取消"那条准则不冲突 ——
    // 那条针对的是会丢数据的动作，这个装的是微软官方运行库、装错了也不伤已有东西。
    focusCancel: false,
  });
  if (!ok) return { installed: false, skipped: true };

  showProgressToast(PROGRESS_KEY, "正在下载并安装 VC++ 运行库…（约 24 MB，安装过程是静默的）");
  try {
    const r = await call("install_vc_runtime");
    if (r && r.ok === false) {
      await showAlert("没能装好", r.message || "未知原因");
      return { installed: false };
    }
    await showAlert("VC++ 运行库已就绪", (r && r.message) || "");
    return { installed: true };
  } finally {
    hideProgressToast(PROGRESS_KEY);
  }
}
