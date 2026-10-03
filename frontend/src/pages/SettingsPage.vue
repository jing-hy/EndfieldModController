<script setup>
// 设置页（对应旧 index.html 的 #tab-settings）。
// ⚠️ 所有表单项都走 `SettingPath / SettingSwitch / SettingSelect`，它们内部按"只发改动的那一个键"
//    调 save_config（旧版语义），所以这里不碰保存细节，只负责分组与按钮。
import { computed, onMounted, ref } from "vue";
import { call } from "../lib/bridge.js";
import { useLogAutoScroll } from "../lib/autoscroll.js";
import { store, applyTheme, THEMES, refreshState } from "../store.js";
import { settings, saveSetting } from "../lib/settings.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Badge from "../components/ui/Badge.vue";
import SettingPath from "../components/ui/SettingPath.vue";
import SettingPathBrowse from "../components/ui/SettingPathBrowse.vue";
import SettingSwitch from "../components/ui/SettingSwitch.vue";
import { showModalDialog, showToast, showProgressToast, hideProgressToast } from "../lib/dialog.js";
import SettingSelect from "../components/ui/SettingSelect.vue";

const RE_INJECTION = [
  { value: "xxmi_extra", label: "经 XXMI 注入库注入（本方案，推荐）" },
  { value: "none", label: "不注入（只跑服装 Mod）" },
  { value: "external", label: "外部注入（旧方案，已废弃）" },
];
const DL_BOOST = [
  { value: "auto", label: "自动（只在慢/抖动时临时并发）" },
  { value: "always", label: "强制并发（连接很差时用）" },
  { value: "never", label: "关闭（只用单连接）" },
];
const DL_LINE = [
  { value: "auto", label: "自动（直连优先，不通才临时换镜像）" },
  { value: "direct", label: "仅直连" },
  { value: "mirror", label: "只用镜像（直连被墙时）" },
];
const THEME_OPTIONS = [
  { value: "light", label: "浅色" }, { value: "dark", label: "深色" },
  { value: "amber", label: "琥珀" }, { value: "cyan", label: "青蓝" },
  { value: "violet", label: "紫罗兰" }, { value: "emerald", label: "翡翠" },
];

// state 里没有 paths：运行目录由 data_root + config 里的相对/绝对路径拼出来
const paths = computed(() => {
  const c = store.state.config || {};
  const root = store.state.data_root || "";
  return { controller: root, reshade: c.reshade_dll || "", staging: c.staging_mods_dir || "", mod_backup: c.mod_backup_dir || "" };
});
// ⚠️ **线路状况**（2026-10-03 修回归：原先硬编码 `computed(() => [])` ⇒ 那一格永远不渲染，
// 用户"下载卡住时不知道为什么"的排查入口就这么没了）。
// 数据源 = `get_download_settings()` 的 `lines`（每条线路的历史速度/可用性/被封锁状态）
// 与 `status`（当前策略/线路模式/是否正在并发加速/上次结果）。
// 展示沿用现有 `Badge` 组件（tone: success/muted/warning/danger），与页面其余部分一致。
const lineStatus = ref([]);
// 渲染 API 的告警文案（同 LaunchPage：vulkan/d3d12 ⇒ 服装 Mod 不生效）
const renderApiText = computed(() => {
  const v = String((store.state.render_api || "")).toLowerCase();
  if (v === "vulkan") return "Vulkan —— 服装 Mod 不生效，请在启动器里选 DirectX 11";
  if (v === "d3d12") return "DirectX 12 —— 服装 Mod 不生效，请在启动器里选 DirectX 11";
  if (v === "d3d11") return "DirectX 11";
  return "未知（还没启动过）";
});
const renderApiWarn = computed(() => {
  const v = String((store.state.render_api || "")).toLowerCase();
  return v === "vulkan" || v === "d3d12";
});
const dlStatus = ref(null);
const lastDownload = computed(() => {
  const s = dlStatus.value && dlStatus.value.last;
  if (!s || (!s.mbps && !s.line)) return "";
  const parts = [];
  if (s.line) parts.push(String(s.line));
  if (s.mbps) parts.push(`${Number(s.mbps).toFixed(2)} MB/s`);
  if (s.threads && Number(s.threads) > 1) parts.push(`临时并发 ${s.threads} 连接`);
  if (s.ok === false) parts.push("失败");
  return parts.join(" · ");
});

async function loadDownloadStatus() {
  try {
    const d = await call("get_download_settings");
    if (!d || typeof d !== "object") return;
    dlStatus.value = d;
    const lines = (d.lines || []).map((l) => ({
      name: String(l.line || ""),
      ok: l.ok === true,
      blocked: !!l.blocked,
      mbps: Number(l.mbps || 0),
      fails: Number(l.fails || 0),
    })).filter((l) => l.name);
    // 有速度的排前面（用户最关心"哪条线路能跑"）
    lines.sort((a, b) => (b.mbps - a.mbps) || (Number(a.blocked) - Number(b.blocked)));
    lineStatus.value = lines;
  } catch (e) { /* 拿不到就不显示，不影响设置页其它部分 */ }
}

async function clearDownloadLines() {
  const r = await run("clear_download_lines");
  if (r && r.ok === false) return;      // run() 已 toast
  showToast("线路记录已清空（下次下载会重新测速）", "success");
  await loadDownloadStatus();
}
// ─────────────────────────────────────────────────────────────────────────────
// ⚠️⚠️ **A10：设置页「启动与诊断」按钮墙的结果原本无处可看**（2026-10-03 补回归）。
//
// 0.9.5 里这一整块 17 个按钮**每个都有可见结果**（0.9.5 的 `app.js` 里逐条写在
// `#init-status` / `#update-status` / `#game-inject-status` 或专门的弹窗里）。
// 换代到 Vue 后只剩 `run(method)` —— 返回值在模板里**一律被丢弃**：
//   * 失败：2026-10-03 我给 `run()` 加了 danger toast（那一半已修）；
//   * **成功：仍然什么都不显示** ⇒ 用户点了"游戏目录体检""检查组件更新""查看启动日志"
//     之后完全不知道结果是什么，功能等于白点。
//
// 这里补一个统一的结果渲染：调后端 → 把返回结构整理成人话 → 弹窗/日志框展示。
// 展示沿用现有 `showModalDialog`（正文是等宽的 <pre>，长路径会自然折行）与 `Btn`。
// ─────────────────────────────────────────────────────────────────────────────

/** 把任意后端返回值整理成可读文本（各接口结构不同，这里做通用兜底 + 针对性美化）。 */
function formatResult(method, r) {
  if (r == null) return "（没有返回内容）";
  if (r.ok === false) return `失败：${r.message || r.reason || "未知原因"}`;
  switch (method) {
    case "read_launch_log": {
      const text = String(r.text || r.log || "").trim();
      if (!text) return "启动日志是空的（可能还没启动过，或日志刚被清过）。";
      // 只给最后 400 行 —— 完整日志用户可以去运行目录看，弹窗里给尾巴最有用
      const lines = text.split("\n");
      const tail = lines.slice(-400).join("\n");
      return `（共 ${lines.length} 行，这里显示最后 ${Math.min(400, lines.length)} 行）\n\n${tail}`;
    }
    case "poser_log_tail": {
      const lines = r.lines || r.tail || [];
      if (!lines.length) return r.message || "没有 Poser 日志（可能还没用过摆姿功能）。";
      return `路径：${r.path || "（未知）"}\n\n` + lines.join("\n");
    }
    case "game_clean_audit": {
      const findings = r.findings || [];
      const head = [
        `游戏目录：${r.game_dir || "（未定位）"}`,
        `第三方注入文件：${r.injections || 0} 个`,
        r.multi_instance ? `⚠ 检测到多个实例（${r.multi_instance}）` : "",
        "",
      ].filter((x) => x !== "");
      if (!findings.length) return head.join("\n") + "没有发现问题。";
      const body = findings.map((f) => {
        const size = f.size_kb ? `　${f.size_kb} KB` : "";
        return `· ${f.label || f.name || f.path}${size}${f.detail ? `　${f.detail}` : ""}`;
      });
      return head.join("\n") + `共 ${findings.length} 项：\n` + body.join("\n");
    }
    case "game_clean_backup_and_clean":
    case "game_clean_restore":
    case "clean_game_injections":
    case "restore_game_injections": {
      const actions = r.actions || r.moved || r.items || [];
      const lines = [r.message || "完成。"];
      if (Array.isArray(actions) && actions.length) {
        lines.push("", `共 ${actions.length} 项：`);
        for (const a of actions.slice(0, 60)) {
          lines.push("· " + (typeof a === "string" ? a
            : (a.label || a.name || a.path || JSON.stringify(a))));
        }
        if (actions.length > 60) lines.push(`…另有 ${actions.length - 60} 项`);
      }
      if (r.backup) lines.push("", `备份位置：${r.backup}`);
      return lines.join("\n");
    }
    case "check_component_updates": {
      const items = r.components || r.items || r.updates || [];
      if (!items.length && !r.report) return r.message || "没有可检查的组件。";
      const list = Array.isArray(items) ? items : Object.values(items);
      const lines = list.map((c) => {
        const cur = c.current || c.installed || "未装";
        const latest = c.latest || c.available || "";
        const tail = c.update_available ? `　→ ${latest}【有新版】` : "　（已是最新）";
        return `· ${c.display || c.name || c.key}：${cur}${latest ? tail : ""}`;
      });
      return lines.length ? lines.join("\n") : (r.message || "检查完成。");
    }
    case "check_app_update": {
      const lines = [];
      if (r.current) lines.push(`当前版本：${r.current}`);
      if (r.latest) lines.push(`最新版本：${r.latest}`);
      if (r.published_at) lines.push(`发布时间：${r.published_at}`);
      if (r.asset_size) lines.push(`更新包大小：${(Number(r.asset_size) / 1048576).toFixed(1)} MB`);
      if (r.update_available) lines.push("", "**有新版本可以更新。**");
      else lines.push("", "已经是最新版。");
      if (r.notes) lines.push("", "更新说明：", String(r.notes).slice(0, 1200));
      return lines.join("\n");
    }
    case "force_close_game": {
      const killed = r.killed || [];
      if (!killed.length) return "没有发现残留的游戏进程。";
      return `已结束 ${killed.length} 个进程：\n` + killed.map((k) => `· ${k}`).join("\n") +
        (r.errors && r.errors.length ? `\n\n有 ${r.errors.length} 项没能结束：\n` +
          r.errors.map((e) => `· ${e}`).join("\n") : "");
    }
    default:
      break;
  }
  // 通用兜底：优先挑常见的"内容字段"，都没有才把 JSON 打出来（截断）
  for (const key of ["message", "text", "log", "summary"]) {
    if (typeof r[key] === "string" && r[key].trim()) return r[key];
  }
  return JSON.stringify(r, null, 1).slice(0, 4000);
}

/** 调后端并把结果**展示出来**（成功也展示 —— 这正是 A10 要补的那一半）。 */
async function showResult(method, title) {
  const r = await run(method);          // 失败已由 run() 给 danger toast
  if (r == null) return r;
  if (r.ok === false) return r;         // 失败不弹两次
  await showModalDialog({
    title: title || "结果",
    message: formatResult(method, r),
    okText: "知道了", showCancel: false,
  });
  await refreshState();
  return r;
}

// 「一键安装/更新全部组件」—— 这是个**长任务**，设置页这边不能只是静默跑完：
// 0.9.5 会先弹确认框（列清会装什么），然后切到依赖页看日志/进度（那里是完整链路）。
// 直接复用依赖页那套（`store.autoStartDeps`），不要再另造一份进度显示。
async function startFullUpdate() {
  const ok = await showModalDialog({
    title: "一键安装/更新全部组件",
    message: [
      "会依次检查并补齐：XXMI 本体 / XXMI Libraries / EFMI / Poser / ReShade 底座 / 内置资产。",
      "",
      "**缺的会下载、旧的有新版会更新**，已经是最新的会跳过。",
      "过程比较长（视网络几分钟到十几分钟）。点「开始」会跳到「依赖」页显示实时日志与进度。",
    ].join("\n"),
    okText: "开始", cancelText: "取消",
  });
  if (!ok) return;
  store.autoStartDeps = true;
  store.tab = "dependencies";
}

// 「更新 ReShade 底座」—— 长耗时，且**成功时原本完全静默**，用户会以为没反应而重复点。
// 这里给 sticky 进度提示 + 结束时如实收尾（成功/失败都说话）。
async function updateReshade() {
  const ok = await showModalDialog({
    title: "更新 ReShade 底座",
    message: [
      "会下载最新的 ReShade 运行库并替换 `d3d12.dll`。",
      "",
      "**替换前会自动备份旧的那份**，出问题可以还原。",
      "游戏正在运行的话，建议先关掉它。",
    ].join("\n"),
    okText: "开始更新", cancelText: "取消",
  });
  if (!ok) return;
  showProgressToast("reshade-update", "正在更新 ReShade 底座…（下载中，可能几分钟）");
  try {
    const r = await call("download_reshade");
    if (r && r.ok === false) showToast(String(r.message || "更新失败"), "danger");
    else showToast(String((r && r.message) || "ReShade 底座已就绪"), "success");
  } catch (e) {
    showToast(String((e && e.message) || "更新失败"), "danger");
  } finally {
    hideProgressToast("reshade-update");
    await refreshState();
  }
}

// 「打开 Mod 备份仓」—— 后端对"不在白名单里的路径"会返回 ok:false 而**不抛异常**，
// 所以不看返回值就是静默失败（0.9.5 会把它写进状态行）。
async function openModBackupDir() {
  const r = await run("open_mod_backup_dir");
  if (r && r.ok === false) showToast(String(r.message || "打不开备份目录"), "danger");
}

// 「一键检测全部」：把自检报告按 0.9.5 的语义整理出来（每条 check + 待人工处理项数）
async function runFullCheck() {
  const r = await run("ensure_initialized");
  if (r == null) return;
  if (r.ok === false) return;
  const checks = r.checks || r.report || {};
  const entries = Array.isArray(checks) ? checks
    : Object.entries(checks).map(([k, v]) => ({ key: k, ...(v || {}) }));
  const lines = entries.map((c) => {
    const mark = c.ok === false ? "✗" : (c.manual ? "!" : "✓");
    const extra = c.message ? `　${c.message}` : "";
    return `${mark} ${c.label || c.key || c.name}${extra}`;
  });
  const actions = r.actions || [];
  const pending = r.pending || [];
  if (actions.length) lines.push("", "已自动处理：", ...actions.map((a) => `· ${a}`));
  if (pending.length) lines.push("", `还有 ${pending.length} 项需要你处理：`,
    ...pending.map((p) => `· ${p}`));
  const bad = entries.filter((c) => c.ok === false).length;
  await showModalDialog({
    title: bad ? `自检完成：${bad} 项有问题` : "自检完成：全部正常",
    message: lines.length ? lines.join("\n") : "自检完成，没有需要处理的内容。",
    okText: "知道了", showCancel: false,
  });
  await refreshState();
}

// 详细状态：一个面板接住各类状态查询，结果落在纯黑日志框里（可复制）
const probeText = ref("点上面的按钮查询：DLSS5 / Poser / 组件版本 / 完整性 / 初始化自检。");
const probeBusy = ref(false);
const PROBES = [
  { m: "dlss5_status", label: "DLSS5 状态" },
  { m: "poser_status", label: "Poser 状态" },
  { m: "component_versions", label: "组件版本" },
  { m: "check_integrity", label: "完整性检查" },
  { m: "first_run_state", label: "初始化自检" },
];
async function probe(method) {
  probeBusy.value = true;
  probeText.value = `正在查询 ${method} …`;
  try {
    const r = await call(method);
    probeText.value = JSON.stringify(r, null, 2);
  } catch (e) {
    probeText.value = `查询失败：${(e && e.message) || e}`;
  } finally {
    probeBusy.value = false;
  }
}

async function changeTheme(v) { await saveSetting("theme", v); applyTheme(v); }
// ⚠️⚠️ **`run()` 绝不能静默**（2026-10-03 用户：「**现在导出诊断包的弹窗也没了**」）。
// 原实现是 `try { return await call(...) } catch { return null }` ——
// 异常被无声吞掉、返回的 `{ok:false}` 也没人检查，于是**本页 18 个按钮**（见模板）
// 全都变成"点了什么反应都没有"：用户既不知道成没成、也不知道为什么没成。
// 现在统一兜底：**失败一定给一条 danger toast**（成功则由各按钮自己给更具体的反馈）。
async function run(method, ...args) {
  try {
    const result = await call(method, ...args);
    if (result && result.ok === false) {
      showToast(String(result.message || result.reason || "操作失败"), "danger");
    }
    return result;
  } catch (e) {
    showToast(String((e && e.message) || e || "操作失败"), "danger");
    return null;
  }
}

// 「导出诊断包」—— **必须告诉用户包在哪**（用户 2026-10-03：「导出诊断包的弹窗也没了」）。
// 后端 `export_diagnostics()` 返回 `{ok, path}`；这里拿到路径后弹窗 + 一键打开所在文件夹。
async function exportDiagnostics() {
  const result = await run("export_diagnostics");
  if (!result || result.ok === false || !result.path) {
    return;   // 失败的 toast 已由 run() 给过
  }
  const path = String(result.path);
  const open = await showModalDialog({
    title: "诊断包已导出",
    message:
      `已生成：\n${path}\n\n` +
      "把它发到 GitHub Issues 或 QQ 群（1045239747，验证答案 jing_hy）就能帮你定位问题。\n\n" +
      "包里含运行日志、配置、注入快照与游戏侧日志，**不含你的 Mod 内容**。",
    okText: "打开所在文件夹", cancelText: "知道了",
  });
  if (open) {
    try { await call("open_path_in_explorer", path); } catch (e) { /* 打不开就算了 */ }
  }
}

// 「依赖清空并重新下载」——用户 2026-10-03 要求：
//   ① 出弹窗确认；② 清空完弹个提示；③ 跳转到依赖页走正常下载流程（含日志）。
// 后端 `reset_dependencies_and_redownload` 只做前两步（还原游戏本体 + 清 runtime/assets
// 并写回路径），它自己的文档里就写着"前端负责第三步的跳转与触发"——之前前端没实现。
async function resetDependencies() {
  const ok = await showModalDialog({
    title: "依赖清空并重新下载",
    message: [
      "会依次做三件事：",
      "① 从备份区还原终末地本体（没做过净化就跳过）；",
      "② 清掉 runtime 与 assets，然后重新下载并展开；",
      "③ 跳到「依赖」页开始一键下载。",
      "",
      "你的 Mod 库和程序本体不受影响。",
      "清完到装好之间，组件列表会先变空，属于正常现象。",
    ].join("\n"),
    // 破坏性动作：按钮文字自解释，默认聚焦在安全项上
    okText: "清空并重新下载",
    cancelText: "取消，什么都不做",
    focusCancel: true,
  });
  if (!ok) return;

  const result = await run("reset_dependencies_and_redownload");
  if (!result || result.ok === false) {
    showToast((result && result.message) || "清空失败，详情见设置页的运行日志", "danger");
    return;
  }

  // 清空完的"动态"提示（用户原话：「清空完弹个动态」）
  showToast("已清空 runtime 与 assets，正在跳到依赖页重新下载…", "success");
  // 跳依赖页并让那边自动开跑（依赖页 onMounted 会读这个标志）
  store.autoStartDeps = true;
  store.tab = "dependencies";
}
// ⚠️ **B10：Mod 备份目录必须走带校验的接口**（见模板里的说明）。
// `set_mod_backup_dir` 会拒绝"落在 Mod 库 / 中转目录里"的位置并保持原值 ——
// 因为备份仓落在库里面时，"同步备份"有可能变成删库（`modbackup._overlaps_library`）。
const backupDirNote = ref("");

async function setModBackupDir(value) {
  backupDirNote.value = "";
  try {
    const r = await call("set_mod_backup_dir", String(value || ""));
    if (r && r.ok === false) {
      backupDirNote.value = String(r.message || "这个位置不能用");
      showToast(backupDirNote.value, "danger");
    } else {
      showToast(r && r.message ? String(r.message) : "备份目录已更新", "success");
    }
  } catch (e) {
    backupDirNote.value = String((e && e.message) || "设置失败");
  }
  await refreshState();
}

async function chooseModBackupDir() {
  backupDirNote.value = "";
  try {
    const r = await call("choose_mod_backup_dir");
    if (r && r.ok === false) {
      if (r.cancelled) return;                       // 用户自己取消，不算错误
      backupDirNote.value = String(r.message || "没能选这个目录");
      showToast(backupDirNote.value, "danger");
      return;
    }
    showToast("备份目录已更新", "success");
  } catch (e) {
    backupDirNote.value = String((e && e.message) || "选择失败");
  }
  await refreshState();
}

// ⚠️ **C9：「还原游戏本体」= 净化（不是"从备份还原"）**（见模板里的说明）。
// 动作对齐 0.9.5：`game_clean_backup_and_clean(true)` —— 先整体备份，再移走第三方插件文件。
// 破坏性动作按用户准则：**写清后果、按钮文字自解释、默认聚焦安全项**。
async function restoreGameToVanilla() {
  const ok = await showModalDialog({
    title: "一键还原游戏本体",
    message: [
      "会把游戏目录里所有**第三方插件文件移走**，恢复成原版状态。",
      "",
      "· 会**先整体备份**，随时可以用「从备份还原游戏目录」搬回来",
      "· loader proxy 会用系统原版文件补回",
      "· Mod 库、配置与已装组件都不受影响",
    ].join("\n"),
    okText: "备份并还原", cancelText: "取消", focusCancel: true,
  });
  if (!ok) return;
  showProgressToast("game-restore", "正在备份并还原游戏本体…（文件较多，请稍候）");
  try {
    const r = await call("game_clean_backup_and_clean", true);
    if (r && r.ok === false) {
      showToast(String(r.message || "还原失败"), "danger");
    } else {
      const actions = (r && (r.actions || r.moved)) || [];
      await showModalDialog({
        title: "游戏本体已还原",
        message: [
          (r && r.message) || "游戏目录已恢复为原版状态。",
          actions.length ? `\n共处理 ${actions.length} 项：` : "",
          ...actions.slice(0, 20).map((a) => "· " + (typeof a === "string" ? a : (a.label || a.name || a.path || ""))),
          actions.length > 20 ? `…另有 ${actions.length - 20} 项` : "",
          r && r.backup ? `\n备份位置：${r.backup}` : "",
        ].filter((x) => x !== "").join("\n"),
        okText: "知道了", showCancel: false,
      });
    }
  } catch (e) {
    showToast(String((e && e.message) || "还原失败"), "danger");
  } finally {
    hideProgressToast("game-restore");
    await refreshState();
  }
}

// 「自动检测」—— 一键找 XXMI / 3DMigoto Loader / 官方启动器 / 游戏本体 / 乳摇工具
//（2026-10-03 补回归：0.9.5 有这个按钮，且每次刷新还会静默回填 detected_*；
//  换代后全丢了，`grep detected_` 在现前端 0 命中 ⇒ 内置了 XXMI 那三个框也一直空着）。
// 回填逻辑收在后端 `autodetect_paths()`：只填**空**字段，不覆盖你手填过的路径。
async function autodetectPaths() {
  const r = await run("autodetect_paths");
  if (!r || r.ok === false) return;              // run() 已经 toast 过
  await store.refreshState();
  const filled = Object.keys(r.filled || {});
  const skipped = Object.keys(r.skipped || {});
  if (filled.length) {
    showToast(`已自动填入：${filled.join("、")}`, "success");
  } else if (skipped.length) {
    showToast(`检测到 ${skipped.length} 项，但都已填过（不覆盖你的设置）`, "info");
  } else {
    showToast("没有检测到可自动填入的路径", "info");
  }
}

onMounted(() => {
  // 线路状况进页面就查一次（0.9.5 的 refreshDownloadStatus 也是打开设置页时刷新）
  loadDownloadStatus();
});

// ⚠️ **不能把 kind 当路径传**（2026-10-03 修）。
// 后端 `open_path_in_explorer(target)` / `open_path(target)` 期望的是**真实路径**，
// 而模板传进来的是 `"controller"` / `"reshade"` / `"staging"` 这类**标签** ⇒
// `Path("controller")` 解析到当前工作目录下、必然"路径不存在" ⇒ 三个按钮全废。
// 对照组：0.9.5 也是先 `call('log')` 拿到 `info.dirs` 再打开。
// `log()` 正好返回 {library, staging, runtime, controller, reshade} 的真实路径。
async function openPath(kind) {
  let path = "";
  try {
    const dirs = await call("log");
    path = String((dirs && dirs[kind]) || "");
  } catch (e) { /* 拿不到就走下面的报错 */ }
  if (!path) {
    showToast(`拿不到「${kind}」的路径`, "danger");
    return;
  }
  const r = await run("open_path_in_explorer", path);
  if (r && r.ok === false) showToast(String(r.message || "打不开这个目录"), "danger");
}

// 诊断详情那块日志自动滚到底（不抢鼠标、没新内容不动）
// ⚠️ 2026-10-03 **删掉了这里的两行残留**：
//     const logBox = ref(null);
//     useLogAutoScroll(logBox, () => logLines.value);
// 本页模板里**根本没有** `logBox` 对应的日志框（只有下面这个 `probeBox`），
// 而 `logLines` 也从没在本页定义过（那个名字属于依赖页，2026-10-03 已统一挪进 store）。
// 于是每次进设置页都会抛 `ReferenceError: logLines is not defined`
// —— 用 headless 抓控制台抓到的（页面还能显示，但脚本在那一步就断了）。
const probeBox = ref(null);
useLogAutoScroll(probeBox, () => probeText);
</script>

<template>
  <div class="space-y-4">
    <!-- 顶部：状态优先 + 主操作唯一。评审指出原来四个按钮里两个都是实心蓝、破坏性操作混在中间。 -->
    <div class="card">
      <div class="card-body">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div class="text-sm font-medium">改完即保存</div>
            <div class="text-xs mt-0.5" style="color: var(--text-muted)">
              下面每一项改动<b>立刻生效并写入 config.json</b>，不需要点保存；留空的项按「自动」处理。
            </div>
          </div>
          <div class="flex flex-wrap gap-2">
            <Btn variant="primary" @click="runFullCheck">一键检测全部</Btn>
            <Btn @click="exportDiagnostics">导出诊断包</Btn>
          </div>
        </div>
      </div>
    </div>

    <!-- 两列（GPT-6 Astra 评审：五个大区连续纵向排列要滚很久，右侧又大片空白）：
         左 = 各设置分组（要改的）；右 = 运行状态与详细状态（要看的，滚动时吸顶）。 -->
    <div class="two-col grid gap-4">
      <div class="space-y-4 min-w-0">

    <Card title="维护操作（会改动文件，请确认后再点）">
      <div class="flex flex-wrap gap-2">
        <!-- ⚠️ **C9：语义要与 0.9.5 一致**（2026-10-03 补回归）。
           0.9.5 的「一键还原游戏本体」是 `game_clean_backup_and_clean(true)` ——
           **先把游戏目录整体备份，再把所有第三方插件文件移走**，恢复到原版状态；
           而换代后这里用了 `game_clean_restore`（= **从备份搬回来**），
           和第 233 行的「从备份还原游戏目录」**变成了同一个 API** ⇒
           "净化"这个动作反而只剩「备份并净化游戏目录」一个入口，
           而新手引导第 4 步指着这个按钮、期望的正是"净化"语义。 -->
        <Btn id="game-restore-btn" @click="restoreGameToVanilla">还原游戏本体</Btn>
        <Btn variant="danger" @click="resetDependencies">依赖清空并重新下载</Btn>
      </div>
      <div class="text-xs mt-2" style="color: var(--text-muted)">
        「还原游戏本体」只从备份区把非原版文件搬回去，不动你的 Mod 库；
        「依赖清空并重新下载」会清掉 runtime 与 assets（<b>保留 Mod 库与 exe</b>）后重新拉取。
      </div>
    </Card>

    <Card title="① 工作区与 Mod 库（相对主路径）">
      <SettingPath k="data_root" label="主路径" readonly placeholder="程序所在目录" hint="程序所在目录，下面这些都相对它" />
      <SettingPath k="runtime_dir" label="runtime 目录" placeholder="runtime" />
      <SettingPathBrowse k="library_dir" label="Mod 库目录" placeholder="library" kind="dir" />
      <SettingSwitch k="mod_backup_enabled" label="Mod 备份（默认开，关了就不备份）"
        hint="关掉后不再把 Mod 库里的 Mod 复制进备份仓；已有的备份一个都不会删（只增不减）。" />
      <!-- ⚠️⚠️ **B10：备份目录要走带校验的接口**（2026-10-03 补回归）。
           0.9.5 对这个字段**特判**走 `set_mod_backup_dir` —— 它会拒绝"落在 Mod 库 /
           中转目录里"的位置并**保持原值**（`modbackup._overlaps_library`），
           因为备份仓一旦落在库里面，"同步备份"就可能变成**删库**。
           换代后它走了通用 `save_config`（直接 setattr），**把这道校验绕过了**
           （现前端 grep `set_mod_backup_dir` / `choose_mod_backup_dir` 全 0 命中）。
           这里恢复成专用控件：写入走 `set_mod_backup_dir`，"选择…"走
           `choose_mod_backup_dir`（后端自己弹原生选目录框）。 -->
      <div class="flex items-center gap-3 py-1.5">
        <span class="w-56 shrink-0 text-sm" title="留空 = 主路径下的 mod-backup（只增不减）">Mod 备份目录</span>
        <input class="field flex-1" :value="settings.mod_backup_dir ?? ''" placeholder="mod-backup"
               @change="setModBackupDir($event.target.value)" />
        <Btn size="sm" @click="chooseModBackupDir">选择…</Btn>
      </div>
      <div v-if="backupDirNote" class="text-xs pb-1" style="color: var(--warn)">{{ backupDirNote }}</div>
      <SettingPathBrowse k="staging_mods_dir" label="Staging Mods 目录" placeholder="留空 = 自动：<主路径>/builtin/XXMI/EFMI/Mods" kind="dir" hint="EFMI 实际加载的位置" />
      <SettingPath k="dependency_manifest" label="依赖清单" placeholder="dependencies.json" />
    </Card>

    <Card title="② 游戏与启动器（留空即自动搜索）">
      <!-- ⚠️ **自动检测**（2026-10-03 补回归）：0.9.5 有这个按钮，且每次刷新状态还会
           静默回填 `detected_*`；换代到 Vue 后两条都丢了 ⇒ 即使内置了 XXMI，
           下面几个框也会一直空着。回填逻辑在后端 `autodetect_paths()`：
           **只填空字段，不覆盖你手填过的**。 -->
      <div class="flex items-center justify-between gap-2 pb-1.5">
        <span class="text-xs" style="color: var(--text-muted)">
          不确定路径就点右边，它会找 XXMI / 3DMigoto Loader / 官方启动器 / 游戏本体
        </span>
        <Btn size="sm" @click="autodetectPaths">自动检测</Btn>
      </div>
      <SettingPathBrowse k="official_launcher" label="官方启动器" placeholder="留空 = 自动搜索 Hypergryph Launcher" kind="file" />
      <SettingPathBrowse k="game_exe" label="Endfield.exe" placeholder="留空 = 自动搜索游戏目录" kind="file" />
      <SettingPathBrowse k="xxmi_launcher" label="XXMI Launcher" placeholder="留空 = 自动搜索" kind="file" />
      <SettingPathBrowse k="migoto_loader" label="3DMigoto Loader（可选）" placeholder="留空 = 用内置 migoto_loader.exe" kind="file" />
    </Card>

    <Card title="③ 组件与注入（留空 = 按主路径自动推导）">
      <SettingPathBrowse k="dlss5_dir" label="DLSS5 / 第一人称目录" placeholder="留空 = 自动：<主路径>/dlss5" kind="dir" />
      <SettingPathBrowse k="reshade_dll" label="ReShade 底座 d3d12.dll" placeholder="留空 = 自动：<主路径>/dlss5/d3d12.dll" kind="file" />
      <SettingPathBrowse k="secondary_motion_dir" label="乳摇工具目录" placeholder="留空 = 自动：<主路径>/secondary_motion" kind="dir" hint="装到别处时填这里" />
      <SettingPathBrowse k="poser_dir" label="Endfield Poser 安装包" placeholder="留空 = 自动：<主路径>/poser" kind="dir" />
      <SettingSelect k="reshade_injection" label="ReShade 注入方式" :options="RE_INJECTION" />
    </Card>

    <Card title="④ 下载与网络">
      <SettingPath k="download_proxy" label="下载代理" placeholder="留空即自动（环境变量 → 系统代理 → 直连）" />
      <SettingSelect k="download_boost" label="下载加速" :options="DL_BOOST" />
      <SettingSelect k="download_line" label="下载线路" :options="DL_LINE" />
      <!-- ⚠️ **线路状况**（2026-10-03 修回归：0.9.5 有，换代后变成硬编码空数组）。
           作用：下载卡住时，这里是"哪条线路能跑、跑到多少"的唯一入口。
           展示沿用现有 Badge / Btn（size="sm"），与页面其余部分风格一致。 -->
      <div class="pt-1">
        <div class="flex items-center justify-between gap-2">
          <span class="text-xs" style="color: var(--text-muted)">
            线路状况{{ lastDownload ? `　上次下载：${lastDownload}` : "（暂无记录，下次下载后会显示实测速度）" }}
          </span>
          <Btn v-if="lineStatus.length" size="sm" @click="clearDownloadLines">清除线路记录</Btn>
        </div>
        <div v-if="lineStatus.length" class="flex flex-wrap gap-1.5 pt-1.5">
          <Badge v-for="l in lineStatus" :key="l.name"
                 :tone="l.blocked ? 'danger' : (l.ok ? 'success' : (l.mbps > 0 ? 'warning' : 'muted'))">
            {{ l.name }}
            {{ l.blocked ? "已封锁" : (l.mbps > 0 ? `${l.mbps.toFixed(2)} MB/s` : (l.ok ? "可用" : "未测速")) }}
            <template v-if="l.fails">（失败 {{ l.fails }} 次）</template>
          </Badge>
        </div>
      </div>
    </Card>

    <Card title="⑤ 开关">
      <SettingSwitch k="use_builtin_runtime" label="使用内置 XXMI/EFMI" />
      <SettingSwitch k="auto_update_dependencies" label="启动前自动更新依赖" />
      <SettingSwitch k="require_admin" label="启动时请求管理员权限" />
      <SettingSwitch k="auto_disable_feed_on_native_dlss" label="游戏自带 DLSS 时自动停用喂帧组件"
        hint="终末地自带 DLSS 时，喂帧组件会与游戏自己的 DLSS 抢同一条 NGX 链路。开启时自检会把它停用（移进 runtime\dlss5\_disabled，可逆）—— 但只有游戏确实跑在 D3D12 时才停：被 XXMI/EFMI 强制 -force_d3d11 时游戏建不出自己的 DLSS，喂帧组件是 DLSS5 的必需环节，此时会保持启用。" />
      <SettingSwitch k="inject_reshade_ui" label="注入统一控制面板（自研 ReShade addon）"
        hint="放进 ReShade 真正读取的目录（d3d12.dll 所在处）。关掉后不注入面板；此时「整合 Mod 快捷键」会拒绝锁键。" />
      <SettingSwitch k="prefer_internal_dependencies" label="依赖包优先用控制器维护的那份"
        hint="RabbitFX 这类依赖：同一时间只允许一份生效。开启时优先用控制器自己维护的 _deps 那份，屏蔽你手动放进库的。" />
      <SettingSwitch k="reshade_panel_font" label="面板自动用系统中文字体"
        hint="ReShade 默认字体只有 ASCII，面板里的中文会显示成方块。开启时（仅在 Font 还为空时）自动指向系统中文字体，写前会备份。" />
    </Card>

    <Card title="⑥ 外观">
      <div class="flex items-center gap-3 py-1.5">
        <span class="w-56 shrink-0 text-sm">主题色</span>
        <select class="field flex-1" :value="settings.theme" @change="changeTheme($event.target.value)">
          <option v-for="o in THEME_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </div>
    </Card>

    <Card title="启动与诊断">
      <div class="flex flex-wrap gap-2">
        <Btn variant="primary" @click="run('launch_official_gui')">启动官方 XXMI / EFMI 界面</Btn>
        <Btn @click="showResult('read_launch_log', '启动日志')">查看启动日志</Btn>
        <Btn @click="exportDiagnostics">导出诊断包</Btn>
        <Btn @click="showResult('poser_log_tail', 'Poser 日志')">打开 Poser 日志</Btn>
        <Btn @click="showResult('force_close_game', '强制结束残留游戏')">强制结束残留游戏</Btn>
      </div>
      <div class="flex flex-wrap gap-2 mt-2">
        <Btn @click="showResult('clean_game_injections', '清理残留注入')">清理残留注入</Btn>
        <Btn @click="showResult('restore_game_injections', '撤销清理')">撤销清理</Btn>
        <Btn @click="showResult('check_component_updates', '组件更新检查')">检查组件更新</Btn>
        <Btn variant="primary" @click="startFullUpdate">一键安装/更新全部组件</Btn>
        <Btn @click="showResult('check_app_update', '程序更新检查')">检查程序更新</Btn>
        <Btn @click="updateReshade">更新 ReShade 底座</Btn>
      </div>
      <div class="flex flex-wrap gap-2 mt-2">
        <Btn @click="showResult('game_clean_audit', '游戏目录体检')">游戏目录体检</Btn>
        <Btn variant="primary" @click="showResult('game_clean_backup_and_clean', '备份并净化游戏目录')">备份并净化游戏目录</Btn>
        <Btn @click="showResult('game_clean_restore', '还原游戏目录')">从备份还原游戏目录</Btn>
        <span class="text-xs self-center" style="color: var(--text-muted)">只移动不删除：先把非原版文件整体备份，再让本体回到原版状态。</span>
      </div>
    </Card>

    <Card title="运行目录">
      <div class="space-y-1.5 text-sm">
        <div v-for="row in [
          { label: 'Controller：', value: paths.controller, kind: 'controller' },
          { label: 'ReShade：', value: paths.reshade, kind: 'reshade' },
          { label: 'Staging：', value: paths.staging, kind: 'staging' },
        ]" :key="row.kind" class="flex items-center gap-2">
          <span class="w-24 shrink-0" style="color: var(--text-muted)">{{ row.label }}</span>
          <code class="flex-1 truncate" style="color: var(--text-muted)">{{ row.value || "—" }}</code>
          <Btn size="sm" :disabled="!row.value" @click="openPath(row.kind)">打开</Btn>
        </div>
        <div class="flex items-center gap-2">
          <span class="w-24 shrink-0" style="color: var(--text-muted)">Mod 备份仓：</span>
          <code class="flex-1 truncate" style="color: var(--text-muted)">{{ paths.mod_backup || "—" }}</code>
          <Btn size="sm" @click="openModBackupDir">打开</Btn>
        </div>
      </div>
    </Card>
      </div>


      <!-- 右栏：状态（滚动时吸顶） -->
      <div class="space-y-4 min-w-0" style="align-self: start; position: sticky; top: 68px">
        <Card title="运行状态">
          <div class="space-y-1.5 text-sm">
            <div class="flex items-center gap-2">
              <span class="w-32 shrink-0" style="color: var(--text-muted)">控制器</span>
              <Badge :tone="store.state.controller_ready ? 'success' : 'warn'">
                {{ store.state.controller_ready ? "已生成 controller.ini" : "还没生成（点启动页「生成控制器」）" }}
              </Badge>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-32 shrink-0" style="color: var(--text-muted)">渲染 API</span>
              <!-- ⚠️ 不能只显示裸值：vulkan/d3d12 时**服装 Mod 不生效**（0.9.5 就是这么写的文案） -->
        <Badge :tone="renderApiWarn ? 'warn' : 'muted'">{{ renderApiText }}</Badge>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-32 shrink-0" style="color: var(--text-muted)">ReShade 面板</span>
              <Badge :tone="store.state.reshade_addon_ready ? 'success' : 'warn'">
                {{ store.state.reshade_addon_ready ? "已就位" : "未就位" }}
              </Badge>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-32 shrink-0" style="color: var(--text-muted)">统一快捷键面板</span>
              <span class="text-xs" style="color: var(--text-muted)">{{ (store.state.hotkey_panel || {}).message || "—" }}</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-32 shrink-0" style="color: var(--text-muted)">Mod 备份仓</span>
              <span class="text-xs" style="color: var(--text-muted)">
                {{ (store.state.mod_backup || {}).count || 0 }} 个 · {{ (store.state.mod_backup || {}).size_text || "0 B" }}
              </span>
            </div>
            <div v-if="store.state.warming" class="text-xs" style="color: var(--text-muted)">后台预热中…（预热完会自动刷新）</div>
          </div>
        </Card>

        <Card title="详细状态">
          <div class="flex flex-wrap gap-2">
            <Btn v-for="p in PROBES" :key="p.m" :disabled="probeBusy" @click="probe(p.m)">{{ p.label }}</Btn>
          </div>
          <div ref="probeBox" class="log-box h-56 mt-3">{{ probeText }}</div>
        </Card>
      </div>
    </div>
  </div>
</template>
