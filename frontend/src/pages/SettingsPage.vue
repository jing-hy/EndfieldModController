<!-- SPDX-License-Identifier: AGPL-3.0-only -->
<script setup>
// 设置页（对应旧 index.html 的 #tab-settings）。
// ⚠️ 所有表单项都走 `SettingPath / SettingSwitch / SettingSelect`，它们内部按"只发改动的那一个键"
//    调 save_config（旧版语义），所以这里不碰保存细节，只负责分组与按钮。
import { computed, onMounted, ref } from "vue";
import { call } from "../lib/bridge.js";
import { useLogAutoScroll } from "../lib/autoscroll.js";
import { store, setTheme, setThemeAccent, refreshState } from "../store.js";
import { t, i18n, setLang } from "../lib/i18n.js";
import { settings, saveSetting, loadSettings } from "../lib/settings.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Badge from "../components/ui/Badge.vue";
import SettingPath from "../components/ui/SettingPath.vue";
import SettingPathBrowse from "../components/ui/SettingPathBrowse.vue";
import SettingSwitch from "../components/ui/SettingSwitch.vue";
import { showModalDialog, showAlert, showToast, showProgressToast, hideProgressToast } from "../lib/dialog.js";
import SettingSelect from "../components/ui/SettingSelect.vue";
import Switch from "../components/ui/Switch.vue";
// ⚠️ 模板与 formatResult 都用到了 humanSize，但本文件从来没有 import 过它 ——
// 模板渲染「Mod 备份仓 · N B」时会抛 ReferenceError（整张卡渲染失败）。补上唯一实现。
import { humanSize } from "../lib/util.js";

const RE_INJECTION = computed(() => [
  { value: "xxmi_extra", label: t("经 XXMI 注入库注入（本方案，推荐）") },
  { value: "none", label: t("不注入（只跑服装 Mod）") },
  { value: "external", label: t("外部注入（旧方案，已废弃）") },
]);
const DL_BOOST = computed(() => [
  { value: "auto", label: t("自动（只在慢/抖动时临时并发）") },
  { value: "always", label: t("强制并发（连接很差时用）") },
  { value: "never", label: t("关闭（只用单连接）") },
]);
const DL_LINE = computed(() => [
  { value: "auto", label: t("自动（直连优先，不通才临时换镜像）") },
  { value: "direct", label: t("仅直连") },
  { value: "mirror", label: t("只用镜像（直连被墙时）") },
]);
// 2026-11-28 用户：「背景色应该和强调色应该分开能选择」——
// 底色只有浅色/深色；强调色单独选（默认蓝 + 四个少见色，默认蓝不额外标"更多"）。
// 界面语言（2026-11-28 用户要求英文版 + 设置页语言切换，默认中文）
const LANG_OPTIONS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
];

const THEME_BASE_OPTIONS = computed(() => [
  { value: "light", label: t("浅色") }, { value: "dark", label: t("深色") },
]);
const THEME_ACCENT_OPTIONS = computed(() => [
  { value: "blue", label: t("默认蓝") }, { value: "amber", label: t("琥珀") },
  { value: "cyan", label: t("青蓝") }, { value: "violet", label: t("紫罗兰") },
  { value: "emerald", label: t("翡翠") },
]);
const ACCENT_HEX = {
  blue: "#5b9dff", amber: "#d9a441", cyan: "#38b6d8", violet: "#8b7bef", emerald: "#35b97e",
};
// 界面预览块：底色 + 当前强调色的色条（「颜色标识不对」的修法：一眼看出明暗 + 强调色）
const THEME_BASE_PREVIEWS = {
  light: { bg: "#ffffff", border: "#e4e4e7" },
  dark: { bg: "#18181b", border: "#27272a" },
};
function currentAccentHex() {
  return ACCENT_HEX[store.themeAccent] || ACCENT_HEX.blue;
}

// 轻量版不含 ReShade：这些设置项/按钮不渲染（后端同样门控，这里只是别让人点空气）。
const isLite = computed(() => ((store.state && store.state.edition) || "full") === "lite");
// 2026-11-28（用户：「开了内置 xxmi 那些配置框应该全部变灰不让填」）：
// 「使用内置 XXMI/EFMI」开着时，XXMI Launcher 路径与 Staging Mods 目录**由程序按内置
// 布局自己决定**（`config.xxmi_launcher_path` 现在也以开关为准）；让用户能填但实际不生效
// 就是那种"看起来能改、其实无效"的坑，所以直接置灰。
const builtinRuntimeOn = computed(() => settings.use_builtin_runtime !== false);

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
// GitHub 镜像源单选列表（2026-11-18）：name="" 是「自动」，"direct" 是「仅直连」
const mirrorList = ref([]);
const mirrorSel = ref("");
// 渲染 API 的告警文案（同 LaunchPage：vulkan/d3d12 ⇒ 服装 Mod 不生效）
const renderApiText = computed(() => {
  const v = String((store.state.render_api || "")).toLowerCase();
  if (v === "vulkan") return t("Vulkan —— 服装 Mod 不生效，请在启动器里选 DirectX 11");
  if (v === "d3d12") return t("DirectX 12 —— 服装 Mod 不生效，请在启动器里选 DirectX 11");
  if (v === "d3d11") return "DirectX 11";
  return t("未知（还没启动过）");
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
  if (s.threads && Number(s.threads) > 1) parts.push(t("临时并发连接") + " × " + s.threads);
  if (s.ok === false) parts.push(t("失败"));
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
    // ★ GitHub 镜像源（2026-11-18 用户要求「加一下 github 镜像表」）：照「选择源」那种
    //   单选列表呈现 —— 每项一个名字 + 地址、选中的打勾、右边写上次实测的速度。
    //   顺序由后端给定（自动 / 仅直连 / 各镜像），别在这里排，免得跟下载器实际优先顺序不一致。
    mirrorList.value = (d.mirrors || []).map((m) => ({
      name: String(m.name || ""),
      label: String(m.label || m.name || t("自动")),
      url: String(m.url || ""),
      hint: String(m.hint || ""),
      selected: m.selected === true,
    }));
    const chosen = mirrorList.value.find((m) => m.selected);
    mirrorSel.value = chosen ? chosen.name : "";
  } catch (e) { /* 拿不到就不显示，不影响设置页其它部分 */ }
}

async function pickMirror(name) {
  const target = String(name == null ? "" : name);
  if (target === mirrorSel.value) return;
  const r = await run("set_download_mirror", target);
  if (!r) return;
  // 后端会回落成合法值（不认识的域名一律当"自动"），所以以**后端返回值**为准
  const chosen = (r.mirrors || []).find((m) => m.selected);
  mirrorSel.value = chosen ? String(chosen.name || "") : "";
  if (target && !chosen) {
    showToast(t("这个镜像源不认识，已经改回「自动」"), "warn");
  } else {
    showToast(target ? t("下载已改用镜像：") + target : t("下载已改回自动选线路"), "success");
  }
  await loadDownloadStatus();
}

async function clearDownloadLines() {
  const r = await run("clear_download_lines");
  if (r && r.ok === false) return;      // run() 已 toast
  showToast(t("线路记录已清空（下次下载会重新测速）"), "success");
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
  if (r == null) return t("（没有返回内容）");
  if (r.ok === false) return t("失败：") + (r.message || r.reason || t("未知原因"));
  switch (method) {
    case "read_launch_log": {
      const text = String(r.text || r.log || "").trim();
      if (!text) return t("启动日志是空的（可能还没启动过，或日志刚被清过）。");
      // 只给最后 400 行 —— 完整日志用户可以去运行目录看，弹窗里给尾巴最有用
      const lines = text.split("\n");
      const tail = lines.slice(-400).join("\n");
      return t("（共") + " " + lines.length + " " + t("行，这里显示最后") + " " + Math.min(400, lines.length) + " " + t("行）") + "\n\n" + tail;
    }
    case "poser_log_tail": {
      const lines = r.lines || r.tail || [];
      if (!lines.length) return r.message || t("没有 Poser 日志（可能还没用过摆姿功能）。");
      return t("路径：") + (r.path || t("（未知）")) + "\n\n" + lines.join("\n");
    }
    case "game_clean_audit": {
      const findings = r.findings || [];
      const head = [
        t("游戏目录：") + (r.game_dir || t("（未定位）")),
        t("第三方注入文件：") + (r.injections || 0) + " " + t("个"),
        r.multi_instance ? t("⚠ 检测到多个实例（") + r.multi_instance + t("）") : "",
        "",
      ].filter((x) => x !== "");
      if (!findings.length) return head.join("\n") + t("没有发现问题。");
      const body = findings.map((f) => {
        // ⚠️ 后端给的是 `size`（字节），前端原来读的是自己编的 `size_kb` ⇒ 永远不显示大小。
        // 用已有的 `humanSize`（lib/util.js，唯一实现）而不是再拼一个单位换算。
        const size = f.size ? `　${humanSize(f.size)}` : "";
        return `· ${f.label || f.name || f.path}${size}${f.detail ? `　${f.detail}` : ""}`;
      });
      return head.join("\n") + findings.length + " " + t("项：") + "\n" + body.join("\n");
    }
    case "game_clean_backup_and_clean":
    case "game_clean_restore":
    case "clean_game_injections":
    case "restore_game_injections": {
      const actions = r.actions || r.moved || r.items || [];
      const lines = [r.message || t("完成。")];
      if (Array.isArray(actions) && actions.length) {
        lines.push("", actions.length + " " + t("项："));
        for (const a of actions.slice(0, 60)) {
          lines.push("· " + (typeof a === "string" ? a
            : (a.label || a.name || a.path || JSON.stringify(a))));
        }
        if (actions.length > 60) lines.push(t("…另有") + " " + (actions.length - 60) + " " + t("项"));
      }
      // ⚠️ 后端返回的是 `backup_dir`（原来的 `r.backup` 恒为 undefined ⇒ **备份位置这一行
      // 永远不显示**，而这是用户唯一能找回被移走文件的线索 —— 违反「必须给出文件在哪」）。
      const backupDir = r.backup_dir || r.backup || "";
      if (backupDir) lines.push("", t("备份位置：") + backupDir);
      return lines.join("\n");
    }
    case "check_component_updates": {
      const items = r.components || r.items || r.updates || [];
      if (!items.length && !r.report) return r.message || t("没有可检查的组件。");
      const list = Array.isArray(items) ? items : Object.values(items);
      const lines = list.map((c) => {
        const cur = c.current || c.installed || t("未装");
        const latest = c.latest || c.available || "";
        const tail = c.update_available ? "　→ " + latest + t("【有新版】") : "　" + t("（已是最新）");
        return `· ${c.display || c.name || c.key}：${cur}${latest ? tail : ""}`;
      });
      return lines.length ? lines.join("\n") : (r.message || t("检查完成。"));
    }
    case "check_app_update": {
      const lines = [];
      if (r.current) lines.push(t("当前版本：") + r.current);
      if (r.latest) lines.push(t("最新版本：") + r.latest);
      if (r.published_at) lines.push(t("发布时间：") + r.published_at);
      if (r.asset_size) lines.push(t("更新包大小：") + (Number(r.asset_size) / 1048576).toFixed(1) + " MB");
      if (r.update_available) lines.push("", "**" + t("有新版本可以更新。") + "**");
      else lines.push("", t("已经是最新版。"));
      if (r.notes) lines.push("", t("更新说明："), String(r.notes).slice(0, 1200));
      return lines.join("\n");
    }
    case "force_close_game": {
      const killed = r.killed || [];
      if (!killed.length) return t("没有发现残留的游戏进程。");
      return t("已结束") + " " + killed.length + " " + t("个进程：") + "\n" + killed.map((k) => `· ${k}`).join("\n") +
        (r.errors && r.errors.length ? "\n\n" + r.errors.length + " " + t("项没能结束：") + "\n" +
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
    title: title || t("结果"),
    message: formatResult(method, r),
    okText: t("知道了"), showCancel: false,
  });
  await refreshState();
  return r;
}

// 「一键安装/更新全部组件」—— 这是个**长任务**，设置页这边不能只是静默跑完：
// 0.9.5 会先弹确认框（列清会装什么），然后切到依赖页看日志/进度（那里是完整链路）。
// 直接复用依赖页那套（`store.autoStartDeps`），不要再另造一份进度显示。
async function startFullUpdate() {
  const ok = await showModalDialog({
    title: t("一键安装/更新全部组件"),
    message: [
      t("会依次检查并补齐：XXMI 本体 / XXMI Libraries / EFMI / Poser / ReShade 底座 / 内置资产。"),
      "",
      t("**缺的会下载、旧的有新版会更新**，已经是最新的会跳过。"),
      t("过程比较长（视网络几分钟到十几分钟）。点「开始」会跳到「依赖」页显示实时日志与进度。"),
    ].join("\n"),
    okText: t("开始"), cancelText: t("先不装"),
  });
  if (!ok) return;
  store.autoStartDeps = true;
  store.tab = "downloads";   // 2026-10-07：下载统一去「下载」页
}

// 「更新 ReShade 底座」—— 长耗时，且**成功时原本完全静默**，用户会以为没反应而重复点。
// 这里给 sticky 进度提示 + 结束时如实收尾（成功/失败都说话）。
async function updateReshade() {
  const ok = await showModalDialog({
    title: t("更新 ReShade 底座"),
    message: [
      t("会下载最新的 ReShade 运行库并替换 `d3d12.dll`。"),
      "",
      t("**替换前会自动备份旧的那份**，出问题可以还原。"),
      t("游戏正在运行的话，建议先关掉它。"),
    ].join("\n"),
    okText: t("开始更新"), cancelText: t("先不更新"),
  });
  if (!ok) return;
  showProgressToast("reshade-update", t("正在更新 ReShade 底座…（下载中，可能几分钟）"));
  try {
    const r = await call("download_reshade");
    if (r && r.ok === false) showToast(String(r.message || t("更新失败")), "danger");
    else showToast(String((r && r.message) || t("ReShade 底座已就绪")), "success");
  } catch (e) {
    showToast(String((e && e.message) || t("更新失败")), "danger");
  } finally {
    hideProgressToast("reshade-update");
    await refreshState();
  }
}

// 「打开 Mod 备份仓」—— 后端对"不在白名单里的路径"会返回 ok:false 而**不抛异常**，
// 所以不看返回值就是静默失败（0.9.5 会把它写进状态行）。
async function openModBackupDir() {
  const r = await run("open_mod_backup_dir");
  if (r && r.ok === false) showToast(String(r.message || t("打不开备份目录")), "danger");
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
  if (actions.length) lines.push("", t("已自动处理："), ...actions.map((a) => `· ${a}`));
  if (pending.length) {
    lines.push("", t("还有") + " " + pending.length + " " + t("项需要你处理："));
    // ⚠️ 后端 `pending` 是**字典列表**（`{key, ok, fixed, manual, message}`），原来写成
    // `` `· ${p}` `` ⇒ 界面上输出一串 **`· [object Object]`**（2026-10-04 修）。
    for (const p of pending) {
      const text = (p && (p.message || p.label)) || (p && p.key) || String(p);
      lines.push(`· ${text}`);
    }
  }
  const bad = entries.filter((c) => c.ok === false).length;
  await showModalDialog({
    title: bad ? t("自检完成：") + bad + " " + t("项有问题") : t("自检完成：全部正常"),
    message: lines.length ? lines.join("\n") : t("自检完成，没有需要处理的内容。"),
    okText: t("知道了"), showCancel: false,
  });
  await refreshState();
}

// 详细状态：一个面板接住各类状态查询，结果落在纯黑日志框里（可复制）
// 装 VC++ 运行库（2026-10-05 加）：ReShade 的插件（DLSS5 喂帧组件）依赖 MSVCP140 /
// VCRUNTIME140。这是**装系统组件**，所以：二次确认 + 默认聚焦"先不装"，来源写死微软官方
// （实测国内可直连），装完把新版本号报出来 —— 用户要的就是"看得见结果"。
async function installVcRuntime() {
  const ok = await showModalDialog({
    title: t("安装 / 更新 VC++ 运行库？"),
    message: [
      t("会从微软官方下载 VC_redist.x64.exe（约 24 MB）并静默安装（/install /quiet /norestart）。"),
      t("来源：https://aka.ms/vs/17/release/vc_redist.x64.exe —— 不是第三方站点、也不是 GitHub。"),
      "",
      t("ReShade 的插件需要它；装完程序会把新版本号报给你。"),
    ].join("\n"),
    okText: t("下载并安装"), cancelText: t("先不装"), focusCancel: true,
  });
  if (!ok) return;
  showProgressToast("vc-runtime", t("正在下载并安装 VC++ 运行库…（约 24 MB，装的时候会静默进行）"));
  try {
    const r = await call("install_vc_runtime");
    if (r && r.ok === false) await showAlert(t("没能装好"), r.message || t("未知原因"));
    else await showAlert(t("VC++ 运行库已就绪"), (r && r.message) || "");
  } finally {
    hideProgressToast("vc-runtime");
  }
}

const probeText = ref("");
const probeBusy = ref(false);
const PROBES = computed(() => [
  { m: "dlss5_status", label: t("DLSS5 状态") },
  { m: "poser_status", label: t("Poser 状态") },
  { m: "jiggle_efmi_status", label: t("EndfieldJiggle 状态") },
  { m: "component_versions", label: t("组件版本") },
  { m: "check_integrity", label: t("完整性检查") },
  { m: "first_run_state", label: t("初始化自检") },
]);
// Lite 下不显示 DLSS5 状态探测（轻量版没有那条链路）
const visibleProbes = computed(() => (
  isLite.value ? PROBES.value.filter((p) => p.m !== "dlss5_status") : PROBES.value
));

async function probe(method) {
  probeBusy.value = true;
  probeText.value = t("正在查询") + " " + method + " …";
  try {
    const r = await call(method);
    probeText.value = JSON.stringify(r, null, 2);
  } catch (e) {
    probeText.value = t("查询失败：") + ((e && e.message) || e);
  } finally {
    probeBusy.value = false;
  }
}

// 主题：走 store 的唯一入口（与侧栏菜单同一个真源，切完两边立刻一致）
async function changeLang(v) { await setLang(v); }
async function changeThemeBase(v) { await setTheme(v); loadSettings(); }
async function changeThemeAccent(v) { await setThemeAccent(v); loadSettings(); }
// ⚠️⚠️ **`run()` 绝不能静默**（2026-10-03 用户：「**现在导出诊断包的弹窗也没了**」）。
// 原实现是 `try { return await call(...) } catch { return null }` ——
// 异常被无声吞掉、返回的 `{ok:false}` 也没人检查，于是**本页 18 个按钮**（见模板）
// 全都变成"点了什么反应都没有"：用户既不知道成没成、也不知道为什么没成。
// 现在统一兜底：**失败一定给一条 danger toast**（成功则由各按钮自己给更具体的反馈）。
async function run(method, ...args) {
  try {
    const result = await call(method, ...args);
    if (result && result.ok === false) {
      showToast(String(result.message || result.reason || t("操作失败")), "danger");
    }
    return result;
  } catch (e) {
    showToast(String((e && e.message) || e || t("操作失败")), "danger");
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
    title: t("诊断包已导出"),
    message:
      t("已生成：") + "\n" + path + "\n\n" +
      // ⚠️ 弹窗正文是**纯文本**渲染（`textContent`）⇒ 这里**不能用 markdown**
      //    （原来写的 `**怎么用**` 会原样带着星号露出来）。
      t("怎么用：") + "\n" +
      t("· 去 GitHub 提 issue 时把它拖进附件（仓库 jing-hy/EndfieldModController）") + "\n" +
      t("· 或发到 QQ 群 1045239747（加群验证答案：jing_hy）") + "\n" +
      // 「让 AI 帮你修」（2026-10-07 用户要求）：UP 在上学，有时间差。
      t("· UP 在上学期间不一定有时间及时修；也可以让 AI 工具（如 DSH，https://deepseek.com/harness ）") + "\n" +
      t("  对着这个开源仓库自行排查修复 —— 提示词见「说明」页的「也可以让 AI 帮你修」") + "\n\n" +
      t("包里含运行日志、配置、注入快照与游戏侧日志，不含你的 Mod 内容。"),
    okText: t("打开所在文件夹"), cancelText: t("知道了"),
    // ⚠️ **C11：把"去提 issue"也做成一个按钮**（0.9.5 的反馈弹窗里有这些入口）。
    extraButtons: [{ text: t("去提 issue"), value: "issue" }],
  });
  if (open === "issue") {
    try { await call("open_external", "https://github.com/jing-hy/EndfieldModController/issues/new"); }
    catch (e) { showToast(t("打不开浏览器，手动访问仓库 Issues 页即可"), "info"); }
  } else if (open) {
    try { await call("open_path_in_explorer", path); } catch (e) { /* 打不开就算了 */ }
  }
}

// 「依赖清空并重新下载」——用户 2026-10-03 要求：
//   ① 出弹窗确认；② 清空完弹个提示；③ 跳转到依赖页走正常下载流程（含日志）。
// 后端 `reset_dependencies_and_redownload` 只做前两步（还原游戏本体 + 清 runtime/assets
// 并写回路径），它自己的文档里就写着"前端负责第三步的跳转与触发"——之前前端没实现。
async function resetDependencies() {
  const ok = await showModalDialog({
    title: t("依赖清空并重新下载"),
    message: [
      t("会依次做三件事："),
      t("① 从备份区还原终末地本体（没做过净化就跳过）；"),
      t("② 清掉 runtime 与 assets，然后重新下载并展开；"),
      t("③ 跳到「下载」页开始一键下载。"),
      "",
      t("你的 Mod 库和程序本体不受影响。"),
      t("清完到装好之间，组件列表会先变空，属于正常现象。"),
    ].join("\n"),
    // 破坏性动作：按钮文字自解释，默认聚焦在安全项上
    okText: t("清空并重新下载"),
    cancelText: t("取消，什么都不做"),
    focusCancel: true,
  });
  if (!ok) return;

  const result = await run("reset_dependencies_and_redownload");
  if (!result || result.ok === false) {
    showToast((result && result.message) || t("清空失败，详情见设置页的运行日志"), "danger");
    return;
  }

  // 清空完的"动态"提示（用户原话：「清空完弹个动态」）
  showToast(t("已清空 runtime 与 assets，正在跳到下载页重新下载…"), "success");
  // 跳**下载页**并让那边自动开跑（下载页 onMounted 读这个标志；2026-10-07 从依赖页搬过去）
  store.autoStartDeps = true;
  store.tab = "downloads";
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
      backupDirNote.value = String(r.message || t("这个位置不能用"));
      showToast(backupDirNote.value, "danger");
    } else {
      showToast(r && r.message ? String(r.message) : t("备份目录已更新"), "success");
    }
  } catch (e) {
    backupDirNote.value = String((e && e.message) || t("设置失败"));
  }
  await refreshState();
}

async function chooseModBackupDir() {
  backupDirNote.value = "";
  try {
    const r = await call("choose_mod_backup_dir");
    if (r && r.ok === false) {
      if (r.cancelled) return;                       // 用户自己取消，不算错误
      backupDirNote.value = String(r.message || t("没能选这个目录"));
      showToast(backupDirNote.value, "danger");
      return;
    }
    showToast(t("备份目录已更新"), "success");
  } catch (e) {
    backupDirNote.value = String((e && e.message) || t("选择失败"));
  }
  await refreshState();
}

// ⚠️ **B14：全局回滚**（见模板里的说明）。动作对齐 0.9.5：
// 删掉 `EndfieldModControllerManaged` staging + 恢复可用的 `d3dx_user.ini` / XXMI 配置备份。
// 破坏性动作按用户准则：确认框写清后果、按钮文字自解释、默认聚焦安全项。
async function globalRollback() {
  const ok = await showModalDialog({
    title: t("回滚控制器产物"),
    message: [
      t("会做两件事："),
      t("① 删除 staging（`EndfieldModControllerManaged`，即控制器生成的那份产物）"),
      t("② 恢复可用的 `d3dx_user.ini` / XXMI 配置备份"),
      "",
      t("**你的 Mod 库、游戏本体、已装组件都不受影响。**"),
      t("回滚后要重新用「一键启动」或「生成控制器」再铺一次。"),
    ].join("\n"),
    okText: t("回滚"), cancelText: t("保持现状"), focusCancel: true,
  });
  if (!ok) return;
  showProgressToast("global-rollback", t("正在回滚控制器产物…"));
  try {
    const r = await call("rollback");
    if (r && r.ok === false) {
      showToast(String(r.message || t("回滚失败")), "danger");
    } else {
      await showModalDialog({
        title: t("已回滚"),
        message: formatResult("rollback", r),
        okText: t("知道了"), showCancel: false,
      });
    }
  } catch (e) {
    showToast(String((e && e.message) || t("回滚失败")), "danger");
  } finally {
    hideProgressToast("global-rollback");
    await refreshState();
  }
}

// ⚠️ **C9：「还原游戏本体」= 净化（不是"从备份还原"）**（见模板里的说明）。
// 动作对齐 0.9.5：`game_clean_backup_and_clean(true)` —— 先整体备份，再移走第三方插件文件。
// 破坏性动作按用户准则：**写清后果、按钮文字自解释、默认聚焦安全项**。
async function restoreGameToVanilla() {
  const ok = await showModalDialog({
    title: t("一键还原游戏本体"),
    message: [
      t("会把游戏目录里所有**第三方插件文件移走**，恢复成原版状态。"),
      "",
      t("· 会**先整体备份**，随时可以用「从备份还原游戏目录」搬回来"),
      t("· loader proxy 会用系统原版文件补回"),
      t("· Mod 库、配置与已装组件都不受影响"),
    ].join("\n"),
    okText: t("备份并还原"), cancelText: t("先不还原"), focusCancel: true,
  });
  if (!ok) return;
  showProgressToast("game-restore", t("正在备份并还原游戏本体…（文件较多，请稍候）"));
  try {
    const r = await call("game_clean_backup_and_clean", true);
    if (r && r.ok === false) {
      showToast(String(r.message || t("还原失败")), "danger");
    } else {
      const actions = (r && (r.actions || r.moved)) || [];
      await showModalDialog({
        title: t("游戏本体已还原"),
        message: [
          (r && r.message) || t("游戏目录已恢复为原版状态。"),
          actions.length ? "\n" + t("共处理") + " " + actions.length + " " + t("项：") : "",
          ...actions.slice(0, 20).map((a) => "· " + (typeof a === "string" ? a : (a.label || a.name || a.path || ""))),
          actions.length > 20 ? t("…另有") + " " + (actions.length - 20) + " " + t("项") : "",
          (r && (r.backup_dir || r.backup)) ? "\n" + t("备份位置：") + (r.backup_dir || r.backup) : "",
        ].filter((x) => x !== "").join("\n"),
        okText: t("知道了"), showCancel: false,
      });
    }
  } catch (e) {
    showToast(String((e && e.message) || t("还原失败")), "danger");
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
  // ⚠️ `store.refreshState()` 不存在（2026-10-04 修）：store 上只有数据字段，
  // refreshState 是 store.js 的**模块级导出**（本文件顶部已 import）。
  // 原来这句抛 `TypeError: store.refreshState is not a function` ⇒ 函数在这里中断，
  // 下面三条 showToast **全部不可达** —— 用户点「自动检测」永远没有任何提示
  // （而且异常还会被上报成一条前端错误）。
  await refreshState();
  const filled = Object.keys(r.filled || {});
  const skipped = Object.keys(r.skipped || {});
  if (filled.length) {
    showToast(t("已自动填入：") + filled.join(t("、")), "success");
  } else if (skipped.length) {
    showToast(t("检测到") + " " + skipped.length + " " + t("项，但都已填过（不覆盖你的设置）"), "info");
  } else {
    showToast(t("没有检测到可自动填入的路径"), "info");
  }
}

onMounted(() => {
  // 线路状况进页面就查一次（0.9.5 的 refreshDownloadStatus 也是打开设置页时刷新）
  loadDownloadStatus();
  // 调试/关于要的环境信息、Web 服务状态（没有桥时静默为空）
  loadDebugInfo();
  loadUiApi();
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
    showToast(t("拿不到这个路径：") + kind, "danger");
    return;
  }
  // 目录还没生成时（例如控制器产物 MC_Controller 要点过「生成控制器」才有），
  // 让后端退到最近的已存在上级目录再打开 —— 不再只丢一句「路径不存在」。
  let r = null;
  try {
    r = await call("open_path_in_explorer", path, true);
  } catch (e) {
    showToast(String((e && e.message) || t("打不开这个目录")), "danger");
    return;
  }
  if (r && r.ok === false) showToast(String(r.message || t("打不开这个目录")), "danger");
  else if (r && r.message) showToast(String(r.message), "info");
}

// 运行目录行：ReShade 那一行只在完整版显示（轻量版没有那条链路）
const runDirs = computed(() => {
  const rows = [
    { label: "Controller", value: paths.value.controller, kind: "controller" },
    { label: "Staging", value: paths.value.staging, kind: "staging" },
  ];
  if (!isLite.value) {
    rows.splice(1, 0, { label: "ReShade", value: paths.value.reshade, kind: "reshade" });
  }
  return rows;
});

// ── 外观：自定义背景图（2026-11-28 用户要求「背景图片」）────────────
// 存储值可能是"数据根相对路径"或绝对路径；这里转成 file:// URL 给预览用。
const backgroundUrl = computed(() => {
  const cfg = (store.state && store.state.config) || {};
  const raw = String(cfg.ui_background_image || "").trim();
  if (!raw) return "";
  const root = String(store.state.data_root || "").replace(/[\\/]+$/, "");
  const isAbs = /^[A-Za-z]:[\\/]/.test(raw) || raw.startsWith("\\\\") || raw.startsWith("/");
  const abs = isAbs ? raw : (root ? root + "\\" + raw.replace(/\//g, "\\") : raw);
  const encoded = encodeURI(abs.replace(/\\/g, "/"))
    .replace(/#/g, "%23").replace(/\?/g, "%3F");
  return "file:///" + encoded.replace(/^\/+/, "");
});

async function chooseBackground() {
  const r = await call("choose_background_image");
  if (!r || r.ok === false) {
    if (!(r && r.cancelled)) showToast(String((r && r.message) || t("没能选择背景图")), "danger");
    return;
  }
  await refreshState();
  loadSettings();
  showToast(t("背景图已设置"), "success");
}

async function clearBackground() {
  const r = await call("clear_background_image");
  if (r && r.ok === false) {
    showToast(String(r.message || t("清除失败")), "danger");
    return;
  }
  await refreshState();
  loadSettings();
  showToast(t("背景图已清除"), "info");
}

// ── 运行日志 / Web 服务 / 调试（2026-11-28，参考 MaaEnd）──────────
const LOG_RETENTION = computed(() => [
  { value: 7, label: t("保留 7 天") },
  { value: 14, label: t("保留 14 天") },
  { value: 30, label: t("保留 30 天") },
  { value: 90, label: t("保留 90 天") },
  { value: 0, label: t("不按时间清理") },
]);
const debugInfo = ref(null);
const uiApi = ref(null);

async function loadDebugInfo() {
  try { debugInfo.value = await call("debug_info"); } catch (e) { debugInfo.value = null; }
}

async function loadUiApi() {
  try { uiApi.value = await call("ui_api_status"); } catch (e) { uiApi.value = null; }
}

async function toggleUiApi() {
  const next = !settings.ui_api_enabled;
  const r = await saveSetting("ui_api_enabled", next);
  const applied = (r && r.ui_api) || null;
  if (applied && applied.ok === false) {
    showToast(String(applied.message || t("Web 服务没能启动")), "danger");
  } else {
    showToast(next ? t("本机 Web 服务已开启") : t("本机 Web 服务已关闭"), next ? "success" : "info");
  }
  await loadUiApi();
}

async function setUiPort(value) {
  const n = Math.max(0, Math.min(65535, Math.floor(Number(value) || 0)));
  await saveSetting("ui_api_port", n);
  await loadUiApi();
}

function setRetention(value) {
  const n = Number(value);
  saveSetting("log_retention_days", Number.isFinite(n) ? n : 14);
}

async function clearLogsNow() {
  const r = await call("clear_run_logs");
  if (!r || r.ok === false) {
    showToast(String((r && r.message) || t("清理失败")), "danger");
    return;
  }
  showToast(String(r.message || t("已清理")), "success");
  await loadDebugInfo();
}

async function openDebugPath(kind) {
  const info = debugInfo.value || {};
  const target = kind === "logs" ? info.logs : (kind === "config" ? info.data_root : "");
  if (!target) {
    showToast(t("拿不到这个路径"), "danger");
    return;
  }
  let r = null;
  try { r = await call("open_path_in_explorer", target, true); } catch (e) { /* 下面统一报 */ }
  if (r && r.ok === false) showToast(String(r.message || t("打不开这个位置")), "danger");
  else if (r && r.message) showToast(String(r.message), "info");
}

async function openExeFolder() {
  const info = debugInfo.value || {};
  if (!info.exe) {
    showToast(t("当前是源码运行，没有 exe 目录"), "info");
    return;
  }
  const r = await call("open_path_in_explorer", String(info.exe), true);
  if (r && r.ok === false) showToast(String(r.message || t("打不开这个位置")), "danger");
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
  <div class="space-y-9">
    <!-- ════════════════════ 通用 ════════════════════ -->
    <section id="settings-section-general" class="space-y-4 scroll-mt-2">
      <h2 class="text-sm font-semibold pb-1 border-b" style="border-color: var(--border)">{{ t("通用") }}</h2>


      <Card :title="t('语言')">
        <div class="flex items-start gap-3 py-1.5 flex-wrap">
          <span class="w-56 shrink-0 text-sm pt-1">{{ t("语言") }}</span>
          <div class="flex flex-wrap gap-2">
            <button v-for="opt in LANG_OPTIONS" :key="opt.value"
                    class="px-3 py-1.5 rounded text-sm"
                    :style="{ border: '1px solid ' + (i18n.lang === opt.value ? 'var(--accent)' : 'var(--border)'),
                              background: i18n.lang === opt.value ? 'var(--accent-soft)' : 'transparent',
                              color: i18n.lang === opt.value ? 'var(--accent)' : 'var(--text)' }"
                    :data-mc-id="'language:' + opt.value"
                    @click="changeLang(opt.value)">{{ opt.label }}</button>
          </div>
        </div>
      </Card>

      <Card :title="t('启动行为')">
        <SettingSwitch k="use_builtin_runtime" :label="t('使用内置 XXMI/EFMI')" />
        <SettingSwitch k="auto_update_dependencies" :label="t('启动前自动更新依赖')" />
        <SettingSwitch k="require_admin" :label="t('启动时请求管理员权限')" />
        <SettingSwitch k="clear_game_injections_on_launch" :label="t('启动前清除游戏目录里的所有第三方注入（先备份）')"
          :hint="t('默认开。每次点「一键启动」时，先把游戏目录里原版不会有的注入痕迹全部移走 —— 不管是不是本程序装的（各种 proxy DLL、plugin 下的插件、3DMigoto 的 d3dx.ini / ShaderFixes、OptiScaler、ReShade 残留、被替换的 nvngx…），再把系统原版补回去；随后自检按你现在的开关把本程序要用的那一份重新铺好，所以功能不会因此失效。移走的东西整体备份在 runtime\\game_backup\\，随时可用「撤销清除」原样放回。游戏正在运行时自动跳过。')" />
        <SettingSwitch k="defender_exclusions_enabled" :label="t('自动把游戏目录 / 程序目录加进 Windows Defender 白名单')"
          :hint="t('默认开。安全软件把文件当威胁隔离掉是本项目已知的问题类（表现是「明明修好了，第二天又缺文件」「游戏突然起不来」）—— 开启后，检测到这两个目录不在 Defender 的排除项里就自动加上，而不是弹窗让你自己去点系统设置。⚠️ 只对 Windows Defender 有效：360 / 火绒这类没有通用的命令行排除接口，只能手动加。⚠️ 代价是这两个目录里的文件不再被 Defender 实时扫描。')" />
        <SettingSwitch k="auto_adopt_manual_mods" :label="t('自动清理 XXMI 里的外来 Mod（收编进库后删掉）')"
          :hint="t('默认开。XXMI 的 Mods 目录只该放本程序的产物；里面出现别的目录时（你手动丢进去的、别的整合包留下的）：先反向同步进 Mod 库（库里已有就只标记、不重复拷），再从 Mods 删掉，并自动勾选显示为开启。⚠️ 为什么必须删：它会和本程序随后生成的同角色 Mod 构成「同角色成对」，游戏会直接崩。关掉则原样保留。')" />
        <SettingSwitch k="prefer_internal_dependencies" :label="t('依赖包优先用控制器维护的那份')"
          :hint="t('RabbitFX 这类依赖：同一时间只允许一份生效。开启时优先用控制器自己维护的 _deps 那份，屏蔽你手动放进库的。')" />
      </Card>

      <Card :title="t('运行日志')">
        <SettingSwitch k="auto_clear_logs" :label="t('启动时自动清理运行日志')"
          :hint="t('只清理 runtime\\logs 下超过「保留天数」的文件；最近日志与诊断包不受影响。')" />
        <div class="flex items-center gap-3 py-1.5">
          <span class="w-56 shrink-0 text-sm">{{ t("保留天数") }}</span>
          <select class="field flex-1" :value="String(settings.log_retention_days ?? 14)"
                  @change="setRetention($event.target.value)">
            <option v-for="o in LOG_RETENTION" :key="o.value" :value="String(o.value)">{{ o.label }}</option>
          </select>
        </div>
        <div class="flex items-center gap-2 pt-1">
          <Btn size="sm" @click="clearLogsNow">{{ t("立即清理一次") }}</Btn>
          <span class="text-xs" style="color: var(--text-muted)">{{ t("按上面的保留天数清理；清理动作本身也会写进运行日志。") }}</span>
        </div>
      </Card>

      <template v-if="!isLite">
        <Card :title="t('ReShade 与 DLSS5（仅完整版）')">
          <SettingSwitch k="auto_disable_feed_on_native_dlss" :label="t('游戏自带 DLSS 时自动停用喂帧组件')"
            :hint="t('终末地自带 DLSS 时，喂帧组件会与游戏自己的 DLSS 抢同一条 NGX 链路。开启时自检会把它停用（移进 runtime\\dlss5\\_disabled，可逆）—— 但只有游戏确实跑在 D3D12 时才停：被 XXMI/EFMI 强制 -force_d3d11 时游戏建不出自己的 DLSS，喂帧组件是 DLSS5 的必需环节，此时会保持启用。')" />
          <SettingSwitch k="inject_reshade_ui" :label="t('注入统一控制面板（自研 ReShade addon）')"
            :hint="t('放进 ReShade 真正读取的目录（d3d12.dll 所在处）。关掉后不注入面板；此时「整合 Mod 快捷键」会拒绝锁键。')" />
          <SettingSwitch k="reshade_panel_font" :label="t('面板自动用系统中文字体')"
            :hint="t('ReShade 默认字体只有 ASCII，面板里的中文会显示成方块。开启时（仅在 Font 还为空时）自动指向系统中文字体，写前会备份。')" />
        </Card>
      </template>
      <div v-else class="text-xs" style="color: var(--text-muted)">
        {{ t("当前是") }}<b>{{ t("轻量版") }}</b>{{ t("：不含 ReShade / DLSS5 / 第一人称 / 统一面板，相关开关与路径都不显示；") }}
        {{ t("游戏目录里已有的 ReShade 残留会在每次启动时被移走（有备份，可还原）。") }}
      </div>
    </section>

    <!-- ════════════════════ 外观 ════════════════════ -->
    <section id="settings-section-appearance" class="space-y-4 scroll-mt-2">
      <h2 class="text-sm font-semibold pb-1 border-b" style="border-color: var(--border)">{{ t("外观") }}</h2>

      <Card :title="t('主题')">
        <div class="flex items-start gap-3 py-1.5 flex-wrap">
          <span class="w-24 shrink-0 text-sm pt-1">{{ t("界面") }}</span>
          <div class="flex flex-wrap gap-2">
            <button v-for="o in THEME_BASE_OPTIONS" :key="o.value"
                    class="flex items-center gap-2 px-3 py-1.5 rounded text-sm"
                    :style="{ border: '1px solid ' + (store.theme === o.value ? 'var(--accent)' : 'var(--border)'),
                              background: store.theme === o.value ? 'var(--accent-soft)' : 'transparent',
                              color: store.theme === o.value ? 'var(--accent)' : 'var(--text)' }"
                    :aria-pressed="store.theme === o.value ? 'true' : 'false'"
                    :data-mc-id="'theme-base:' + o.value"
                    @click="changeThemeBase(o.value)">
              <span class="shrink-0"
                    :style="{ width: '22px', height: '22px', borderRadius: '6px', overflow: 'hidden',
                              background: THEME_BASE_PREVIEWS[o.value].bg,
                              border: '1px solid ' + THEME_BASE_PREVIEWS[o.value].border,
                              display: 'flex', alignItems: 'flex-end' }">
                <span :style="{ display: 'block', width: '100%', height: '7px',
                                background: currentAccentHex() }"></span>
              </span>
              <span>{{ o.label }}</span>
            </button>
          </div>
        </div>
        <div class="flex items-start gap-3 py-1.5 flex-wrap">
          <span class="w-24 shrink-0 text-sm pt-1">{{ t("强调色") }}</span>
          <div class="flex flex-wrap gap-2">
            <button v-for="o in THEME_ACCENT_OPTIONS" :key="o.value"
                    class="flex items-center gap-2 px-3 py-1.5 rounded text-sm"
                    :style="{ border: '1px solid ' + (store.themeAccent === o.value ? 'var(--accent)' : 'var(--border)'),
                              background: store.themeAccent === o.value ? 'var(--accent-soft)' : 'transparent',
                              color: store.themeAccent === o.value ? 'var(--accent)' : 'var(--text)' }"
                    :aria-pressed="store.themeAccent === o.value ? 'true' : 'false'"
                    :data-mc-id="'theme-accent:' + o.value"
                    @click="changeThemeAccent(o.value)">
              <span class="shrink-0"
                    :style="{ width: '14px', height: '14px', borderRadius: '999px',
                              background: ACCENT_HEX[o.value] }"></span>
              <span>{{ o.label }}</span>
            </button>
          </div>
        </div>
        <div class="text-xs mt-2" style="color: var(--text-muted)">
          {{ t("背景（浅色 / 深色）与强调色分开选，切完立刻生效、刷新后保留；强调色只影响按钮、选中行与开关。") }}
        </div>
      </Card>

      <Card :title="t('背景图片')">
        <div class="flex items-start gap-3 py-1.5 flex-wrap">
          <span class="w-56 shrink-0 text-sm pt-1">{{ t("自定义背景") }}</span>
          <div class="flex items-center gap-3 flex-wrap">
            <div v-if="backgroundUrl" class="rounded overflow-hidden shrink-0"
                 style="width: 132px; height: 74px; border: 1px solid var(--border); background: var(--surface-2)">
              <img :src="backgroundUrl" :alt="t('背景预览')" style="width: 100%; height: 100%; object-fit: cover" />
            </div>
            <div class="flex flex-col gap-1">
              <div class="flex gap-2">
                <Btn size="sm" @click="chooseBackground">{{ t("选择图片…") }}</Btn>
                <Btn v-if="store.state.config && store.state.config.ui_background_image" size="sm"
                     @click="clearBackground">{{ t("清除") }}</Btn>
              </div>
              <span class="text-xs" style="color: var(--text-muted)">{{ t("支持 png / jpg / webp / bmp / gif；留空 = 纯色底。") }}</span>
            </div>
          </div>
        </div>
        <div class="flex items-center gap-3 py-1.5">
          <span class="w-56 shrink-0 text-sm">{{ t("背景不透明度") }}</span>
          <input type="range" min="0" max="100" class="flex-1"
                 :value="settings.ui_background_opacity ?? 80"
                 @change="saveSetting('ui_background_opacity', Number($event.target.value))" />
          <span class="w-10 text-right text-xs" style="color: var(--text-muted)">{{ settings.ui_background_opacity ?? 80 }}%</span>
        </div>
        <div class="text-xs" style="color: var(--text-muted)">
          {{ t("背景图铺在页面底色之上、卡片之下；卡片保持不透明，保证文字可读。") }}
        </div>
      </Card>
    </section>

    <!-- ════════════════════ 路径 ════════════════════ -->
    <section id="settings-section-paths" class="space-y-4 scroll-mt-2">
      <h2 class="text-sm font-semibold pb-1 border-b" style="border-color: var(--border)">{{ t("路径") }}</h2>

      <Card :title="t('工作区与 Mod 库（相对主路径）')">
        <div class="text-xs pb-1.5 space-y-0.5" style="color: var(--text-muted)">
          <div>{{ t("程序所在目录：") }}<code>{{ store.state.data_root || t("（未知）") }}</code></div>
          <div v-if="store.state.config && store.state.config.data_root && store.state.config.data_root !== store.state.data_root"
               style="color: var(--warn)">
            {{ t("上次运行记录的是：") }}<code>{{ store.state.config.data_root }}</code>
            {{ t("—— 与当前程序位置不同（程序搬过家？保存一次设置就会以当前位置为准）") }}
          </div>
        </div>
        <SettingPath k="data_root" :label="t('主路径')" readonly :placeholder="t('程序所在目录')" :hint="t('程序所在目录，下面这些都相对它')" />
        <SettingPath k="runtime_dir" :label="t('runtime 目录')" placeholder="runtime" />
        <SettingPathBrowse k="library_dir" :label="t('Mod 库目录')" placeholder="library" kind="dir" />
        <SettingSwitch k="mod_backup_enabled" :label="t('Mod 备份（默认开，关了就不备份）')"
          :hint="t('关掉后不再把 Mod 库里的 Mod 复制进备份仓；已有的备份一个都不会删（只增不减）。')" />
        <div class="flex items-center gap-3 py-1.5">
          <span class="w-56 shrink-0 text-sm" :title="t('留空 = 主路径下的 mod-backup（只增不减）')">{{ t("Mod 备份目录") }}</span>
          <input class="field flex-1" :value="settings.mod_backup_dir ?? ''" placeholder="mod-backup"
                 @change="setModBackupDir($event.target.value)" />
          <Btn size="sm" @click="chooseModBackupDir">{{ t("选择…") }}</Btn>
        </div>
        <div v-if="backupDirNote" class="text-xs pb-1" style="color: var(--warn)">{{ backupDirNote }}</div>
        <SettingPathBrowse k="staging_mods_dir" :label="t('Staging Mods 目录')" :placeholder="t('留空 = 自动：<主路径>/builtin/XXMI/EFMI/Mods')" kind="dir" :hint="t('EFMI 实际加载的位置')" :disabled="builtinRuntimeOn" />
        <SettingPath k="dependency_manifest" :label="t('依赖清单')" placeholder="dependencies.json" />
      </Card>

      <Card :title="t('游戏与启动器（留空即自动搜索）')">
        <div class="flex items-center justify-between gap-2 pb-1.5">
          <span class="text-xs" style="color: var(--text-muted)">
            {{ t("不确定路径就点右边，它会找 XXMI / 3DMigoto Loader / 官方启动器 / 游戏本体") }}
          </span>
          <Btn size="sm" @click="autodetectPaths">{{ t("自动检测") }}</Btn>
        </div>
        <SettingPathBrowse k="official_launcher" :label="t('官方启动器')" :placeholder="t('留空 = 自动搜索 Hypergryph Launcher')" kind="file" />
        <SettingPathBrowse k="game_exe" label="Endfield.exe" :placeholder="t('留空 = 自动搜索游戏目录')" kind="file" />
        <SettingPathBrowse k="xxmi_launcher" label="XXMI Launcher" :placeholder="t('留空 = 自动搜索')" kind="file" :disabled="builtinRuntimeOn" />
        <SettingPathBrowse k="migoto_loader" :label="t('3DMigoto Loader（可选）')" :placeholder="t('留空 = 用内置 migoto_loader.exe')" kind="file" />
      </Card>

      <Card :title="t('组件目录（留空 = 按主路径自动推导）')">
        <SettingPathBrowse k="secondary_motion_dir" :label="t('乳摇工具目录')" :placeholder="t('留空 = 自动：<主路径>/secondary_motion')" kind="dir" :hint="t('装到别处时填这里')" />
        <SettingPathBrowse k="poser_dir" :label="t('Endfield Poser 安装包')" :placeholder="t('留空 = 自动：<主路径>/poser')" kind="dir" />
        <template v-if="!isLite">
          <SettingPathBrowse k="dlss5_dir" :label="t('DLSS5 / 第一人称目录')" :placeholder="t('留空 = 自动：<主路径>/dlss5')" kind="dir" />
          <SettingPathBrowse k="reshade_dll" :label="t('ReShade 底座 d3d12.dll')" :placeholder="t('留空 = 自动：<主路径>/dlss5/d3d12.dll')" kind="file" />
          <SettingSelect k="reshade_injection" :label="t('ReShade 注入方式')" :options="RE_INJECTION" />
        </template>
      </Card>

      <Card :title="t('运行目录')">
        <div class="space-y-1.5 text-sm">
          <div v-for="row in runDirs" :key="row.kind" class="flex items-center gap-2">
            <span class="w-24 shrink-0" style="color: var(--text-muted)">{{ row.label }}</span>
            <code class="flex-1 truncate" style="color: var(--text-muted)">{{ row.value || "—" }}</code>
            <Btn size="sm" :disabled="!row.value" @click="openPath(row.kind)">{{ t("打开") }}</Btn>
          </div>
          <div class="flex items-center gap-2">
            <span class="w-24 shrink-0" style="color: var(--text-muted)">{{ t("Mod 备份仓：") }}</span>
            <code class="flex-1 truncate" style="color: var(--text-muted)">{{ paths.mod_backup || "—" }}</code>
            <Btn size="sm" @click="openModBackupDir">{{ t("打开") }}</Btn>
          </div>
        </div>
      </Card>
    </section>

    <!-- ════════════════════ 下载 ════════════════════ -->
    <section id="settings-section-downloads" class="space-y-4 scroll-mt-2">
      <h2 class="text-sm font-semibold pb-1 border-b" style="border-color: var(--border)">{{ t("下载") }}</h2>
      <Card :title="t('下载与网络')">
        <SettingPath k="download_proxy" :label="t('下载代理')" :placeholder="t('留空即自动（环境变量 → 系统代理 → 直连）')" />
        <SettingSelect k="download_boost" :label="t('下载加速')" :options="DL_BOOST" />
        <SettingSelect k="download_line" :label="t('下载线路')" :options="DL_LINE" />
        <div class="pt-2" role="radiogroup" :aria-label="t('GitHub 镜像源')">
          <div class="text-xs mb-1" style="color: var(--text-muted)">
            {{ t("GitHub 镜像源（下载走哪一条；速度是上次实测，选「自动」就会自己挑快的）") }}
          </div>
          <button v-for="m in mirrorList" :key="m.name || 'auto'"
                  type="button" role="radio"
                  :aria-checked="mirrorSel === m.name ? 'true' : 'false'"
                  class="w-full flex items-center gap-2 px-2 py-1.5 rounded text-left text-sm"
                  :style="{ background: mirrorSel === m.name ? 'var(--accent-soft)' : 'transparent',
                            color: mirrorSel === m.name ? 'var(--accent)' : 'var(--text-muted)' }"
                  @click="pickMirror(m.name)">
            <span class="shrink-0" aria-hidden="true">{{ mirrorSel === m.name ? "●" : "○" }}</span>
            <span class="shrink-0">{{ m.label }}</span>
            <span v-if="m.url" class="shrink-0 text-xs opacity-70 truncate">{{ m.url }}</span>
            <span class="ml-auto shrink-0 text-xs opacity-70">{{ m.hint }}</span>
          </button>
          <div v-if="!mirrorList.length" class="text-xs" style="color: var(--text-muted)">
            {{ t("（读不到镜像表 —— 稍后重试；不影响下载，下载器会按「自动」自己挑线路）") }}
          </div>
        </div>
        <div class="pt-1">
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs" style="color: var(--text-muted)">
              {{ t("线路状况") }}{{ lastDownload ? "　" + t("上次下载：") + lastDownload : t("（暂无记录，下次下载后会显示实测速度）") }}
            </span>
            <Btn v-if="lineStatus.length" size="sm" @click="clearDownloadLines">{{ t("清除线路记录") }}</Btn>
          </div>
          <div v-if="lineStatus.length" class="flex flex-wrap gap-1.5 pt-1.5">
            <Badge v-for="l in lineStatus" :key="l.name"
                   :tone="l.blocked ? 'danger' : (l.ok ? 'success' : (l.mbps > 0 ? 'warning' : 'muted'))">
              {{ l.name }}
              {{ l.blocked ? t("已封锁") : (l.mbps > 0 ? l.mbps.toFixed(2) + " MB/s" : (l.ok ? t("可用") : t("未测速"))) }}
              <template v-if="l.fails">{{ t("（失败") }} {{ l.fails }} {{ t("次）") }}</template>
            </Badge>
          </div>
        </div>
      </Card>
    </section>

    <!-- ════════════════════ Web 服务 ════════════════════ -->
    <section id="settings-section-webserver" class="space-y-4 scroll-mt-2">
      <h2 class="text-sm font-semibold pb-1 border-b" style="border-color: var(--border)">{{ t("Web 服务") }}</h2>
      <Card :title="t('本机 Web 服务（UI 自动化 API）')">
        <div class="switch-row" @click="toggleUiApi">
          <div class="min-w-0">
            <div class="font-medium">{{ t("启用本机 Web 服务") }}</div>
            <div class="text-xs mt-0.5" style="color: var(--text-muted)">
              {{ t("默认关闭。开启后只绑 127.0.0.1，脚本 / AI 可以通过它切换页面、点开关、滚列表") }}
              {{ t("（接口说明见 docs/ui-automation.md）。") }}
            </div>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <span class="switch-state">{{ settings.ui_api_enabled ? t("已开启") : t("已关闭") }}</span>
            <Switch :model-value="!!settings.ui_api_enabled" @update:model-value="toggleUiApi" />
          </div>
        </div>
        <div class="flex items-center gap-3 py-1.5">
          <span class="w-56 shrink-0 text-sm">{{ t("端口") }}</span>
          <input class="field flex-1" type="number" min="0" max="65535"
                 :value="settings.ui_api_port ?? 0"
                 @change="setUiPort($event.target.value)" />
          <span class="text-xs shrink-0" style="color: var(--text-muted)">{{ t("0 = 每次启动随机") }}</span>
        </div>
        <div class="text-xs space-y-1 pt-1" style="color: var(--text-muted)">
          <div>{{ t("状态：") }}<b :style="{ color: (uiApi && uiApi.running) ? 'var(--success)' : 'var(--text-muted)' }">{{ (uiApi && uiApi.running) ? t("运行中") : t("未运行") }}</b>
            <template v-if="uiApi && uiApi.url"> · {{ t("地址") }} <code>{{ uiApi.url }}</code></template>
          </div>
          <div v-if="uiApi && uiApi.token_file">{{ t("token 文件：") }}<code>{{ uiApi.token_file }}</code></div>
          <div>{{ t("开关 / 端口改完") }}<b>{{ t("立即生效") }}</b>{{ t("，不需要重启程序；启动失败只会留一行日志，不影响界面。") }}</div>
        </div>
      </Card>
    </section>

    <!-- ════════════════════ 维护 ════════════════════ -->
    <section id="settings-section-maintenance" class="space-y-4 scroll-mt-2">
      <h2 class="text-sm font-semibold pb-1 border-b" style="border-color: var(--border)">{{ t("维护") }}</h2>

      <Card :title="t('运行状态')">
        <div class="space-y-1.5 text-sm">
          <div class="flex items-center gap-2">
            <span class="w-32 shrink-0" style="color: var(--text-muted)">{{ t("控制器") }}</span>
            <Badge :tone="store.state.controller_ready ? 'success' : 'warn'">
              {{ store.state.controller_ready ? t("已生成 controller.ini") : t("还没生成（点一次「一键启动」会自动生成）") }}
            </Badge>
          </div>
          <div class="flex items-center gap-2">
            <span class="w-32 shrink-0" style="color: var(--text-muted)">{{ t("渲染 API") }}</span>
            <Badge :tone="renderApiWarn ? 'warn' : 'muted'">{{ renderApiText }}</Badge>
          </div>
          <div v-if="!isLite" class="flex items-center gap-2">
            <span class="w-32 shrink-0" style="color: var(--text-muted)">{{ t("ReShade 面板") }}</span>
            <Badge :tone="store.state.reshade_addon_ready ? 'success' : 'warn'">
              {{ store.state.reshade_addon_ready ? t("已就位") : t("未就位") }}
            </Badge>
          </div>
          <div v-if="!isLite" class="flex items-center gap-2">
            <span class="w-32 shrink-0" style="color: var(--text-muted)">{{ t("统一快捷键面板") }}</span>
            <span class="text-xs" style="color: var(--text-muted)">{{ (store.state.hotkey_panel || {}).message || "—" }}</span>
          </div>
          <div class="flex items-center gap-2">
            <span class="w-32 shrink-0" style="color: var(--text-muted)">{{ t("Mod 备份仓") }}</span>
            <span class="text-xs" style="color: var(--text-muted)">
              {{ (store.state.mod_backup || {}).count || 0 }} {{ t("个") }} ·
              {{ humanSize((store.state.mod_backup || {}).bytes) }}
            </span>
          </div>
          <div v-if="store.state.warming" class="text-xs" style="color: var(--text-muted)">{{ t("后台预热中…（预热完会自动刷新）") }}</div>
        </div>
      </Card>

      <Card :title="t('维护操作（会改动文件，请确认后再点）')">
        <div class="flex flex-wrap gap-2">
          <Btn id="game-restore-btn" @click="restoreGameToVanilla">{{ t("还原游戏本体") }}</Btn>
          <Btn variant="danger" @click="resetDependencies">{{ t("依赖清空并重新下载") }}</Btn>
          <Btn @click="globalRollback">{{ t("回滚控制器产物") }}</Btn>
        </div>
        <div class="text-xs mt-2" style="color: var(--text-muted)">
          {{ t("「还原游戏本体」只从备份区把非原版文件搬回去，不动你的 Mod 库；") }}
          {{ t("「依赖清空并重新下载」会清掉 runtime 与 assets（") }}<b>{{ t("保留 Mod 库与 exe") }}</b>{{ t("）后重新拉取。") }}
        </div>
      </Card>

      <Card :title="t('组件与诊断')">
        <div class="flex flex-wrap gap-2">
          <Btn variant="primary" @click="runFullCheck">{{ t("一键检测全部") }}</Btn>
          <Btn @click="exportDiagnostics">{{ t("导出诊断包") }}</Btn>
          <Btn @click="showResult('read_launch_log', t('启动日志'))">{{ t("查看启动日志") }}</Btn>
          <Btn @click="showResult('poser_log_tail', t('Poser 日志'))">{{ t("打开 Poser 日志") }}</Btn>
          <Btn @click="run('launch_official_gui')">{{ t("启动官方 XXMI / EFMI 界面") }}</Btn>
          <Btn @click="run('open_jiggle_efmi_upstream')">{{ t("EndfieldJiggle 上游仓库") }}</Btn>
          <Btn @click="showResult('force_close_game', t('强制结束残留游戏'))">{{ t("强制结束残留游戏") }}</Btn>
        </div>
        <div class="flex flex-wrap gap-2 mt-2">
          <Btn @click="showResult('clear_all_game_injections', t('清除所有第三方注入'))">{{ t("清除所有第三方注入（先备份）") }}</Btn>
          <Btn @click="showResult('restore_all_game_injections', t('撤销清除'))">{{ t("撤销清除（还原备份）") }}</Btn>
          <Btn @click="showResult('check_component_updates', t('组件更新检查'))">{{ t("检查组件更新") }}</Btn>
          <Btn variant="primary" @click="startFullUpdate">{{ t("一键安装/更新全部组件") }}</Btn>
          <Btn @click="showResult('check_app_update', t('程序更新检查'))">{{ t("检查程序更新") }}</Btn>
          <Btn v-if="!isLite" @click="updateReshade">{{ t("更新 ReShade 底座") }}</Btn>
        </div>
        <div class="flex flex-wrap gap-2 mt-2">
          <Btn @click="showResult('game_clean_audit', t('游戏目录体检'))">{{ t("游戏目录体检") }}</Btn>
          <Btn variant="primary" @click="showResult('game_clean_backup_and_clean', t('备份并净化游戏目录'))">{{ t("备份并净化游戏目录") }}</Btn>
          <Btn @click="showResult('game_clean_restore', t('还原游戏目录'))">{{ t("从备份还原游戏目录") }}</Btn>
          <span class="text-xs self-center" style="color: var(--text-muted)">{{ t("只移动不删除：先把非原版文件整体备份，再让本体回到原版状态。") }}</span>
        </div>
        <div v-if="!isLite" class="flex flex-wrap gap-2 mt-2">
          <Btn @click="showResult('vc_runtime_status', t('VC++ 运行库'))">{{ t("检查 VC++ 运行库") }}</Btn>
          <Btn @click="installVcRuntime">{{ t("安装 / 更新 VC++ 运行库") }}</Btn>
          <span class="text-xs self-center" style="color: var(--text-muted)">{{ t("ReShade 的插件依赖它；走微软官方下载（国内可直连），装完会回报版本。") }}</span>
        </div>
      </Card>
    </section>

    <!-- ════════════════════ 调试 ════════════════════ -->
    <section id="settings-section-debug" class="space-y-4 scroll-mt-2">
      <h2 class="text-sm font-semibold pb-1 border-b" style="border-color: var(--border)">{{ t("调试") }}</h2>

      <Card :title="t('运行环境')">
        <div v-if="!debugInfo" class="text-xs" style="color: var(--text-muted)">{{ t("读取中…（没有桥时拿不到）") }}</div>
        <div v-else class="space-y-1.5 text-sm">
          <div class="flex gap-2">
            <span class="w-32 shrink-0" style="color: var(--text-muted)">{{ t("版本") }}</span>
            <code>{{ debugInfo.version }}（{{ debugInfo.edition_label }}）</code>
          </div>
          <div class="flex gap-2">
            <span class="w-32 shrink-0" style="color: var(--text-muted)">{{ t("运行方式") }}</span>
            <span>{{ debugInfo.frozen ? t("打包 exe") : t("源码运行") }}</span>
          </div>
          <div class="flex gap-2">
            <span class="w-32 shrink-0" style="color: var(--text-muted)">{{ t("系统") }}</span>
            <span class="break-all">{{ debugInfo.os }} · {{ debugInfo.arch }}</span>
          </div>
          <div class="flex gap-2">
            <span class="w-32 shrink-0" style="color: var(--text-muted)">Python / WebView</span>
            <span>{{ debugInfo.python }} / {{ debugInfo.webview || "—" }}</span>
          </div>
          <div class="flex gap-2">
            <span class="w-32 shrink-0" style="color: var(--text-muted)">{{ t("程序目录") }}</span>
            <code class="break-all">{{ debugInfo.exe || t("（源码运行）") }}</code>
          </div>
          <div class="flex gap-2">
            <span class="w-32 shrink-0" style="color: var(--text-muted)">{{ t("数据根") }}</span>
            <code class="break-all">{{ debugInfo.data_root }}</code>
          </div>
          <div class="flex gap-2">
            <span class="w-32 shrink-0" style="color: var(--text-muted)">{{ t("日志目录") }}</span>
            <code class="break-all">{{ debugInfo.logs }}</code>
          </div>
        </div>
        <div class="flex flex-wrap gap-2 mt-3">
          <Btn @click="openDebugPath('logs')">{{ t("打开日志目录") }}</Btn>
          <Btn @click="openDebugPath('config')">{{ t("打开数据根") }}</Btn>
          <Btn @click="openExeFolder">{{ t("打开程序目录") }}</Btn>
          <Btn @click="clearLogsNow">{{ t("立即清理运行日志") }}</Btn>
        </div>
      </Card>

      <Card :title="t('详细状态')">
        <div class="flex flex-wrap gap-2">
          <Btn v-for="p in visibleProbes" :key="p.m" :disabled="probeBusy" @click="probe(p.m)">{{ p.label }}</Btn>
        </div>
        <div ref="probeBox" class="log-box h-56 mt-3">{{ probeText || t("点上面的按钮查询：DLSS5 / Poser / 组件版本 / 完整性 / 初始化自检。") }}</div>
      </Card>
    </section>

    <!-- ════════════════════ 关于 ════════════════════ -->
    <section id="settings-section-about" class="space-y-4 scroll-mt-2">
      <h2 class="text-sm font-semibold pb-1 border-b" style="border-color: var(--border)">{{ t("关于") }}</h2>

      <Card :title="t('关于 终末地 Mod 管理器')">
        <div class="space-y-1.5 text-sm">
          <div class="text-base font-semibold">{{ t("终末地 Mod 管理器") }}</div>
          <div class="text-xs" style="color: var(--text-muted)">
            {{ t("版本") }} {{ debugInfo ? debugInfo.version : "—" }} · {{ debugInfo ? debugInfo.edition_label : "—" }}
          </div>
          <div class="text-xs leading-6 pt-1" style="color: var(--text-muted)">
            {{ t("《明日方舟：终末地》Mod 管理器：编排 XXMI / EFMI / ReShade 等组件，负责 Mod 导入、同角色互斥、启动自检与故障排查。完整版含 DLSS5 / 第一人称 / 统一面板；轻量版不含 ReShade 链路，其余功能一致。") }}
          </div>
        </div>
        <div class="flex flex-wrap gap-2 mt-3">
          <Btn @click="showResult('check_app_update', t('程序更新检查'))">{{ t("检查程序更新") }}</Btn>
          <Btn @click="run('open_external', 'https://github.com/jing-hy/EndfieldModController')">{{ t("项目主页") }}</Btn>
          <Btn @click="run('open_external', 'https://github.com/jing-hy/EndfieldModController/issues')">{{ t("问题反馈") }}</Btn>
        </div>
      </Card>

      <Card :title="t('许可与致谢')">
        <ul class="list-disc pl-5 space-y-1.5 text-sm leading-6">
          <li>{{ t("本程序：") }}<b>AGPL-3.0-only</b>{{ t("。第三方组件（XXMI / EFMI / ReShade / RenoDX / DLSS5-Feeder / iMMERSE 等）均为各自作者所有，许可与版权见 README 第九节。") }}</li>
          <li>{{ t("QQ 群：") }}<code>1045239747</code>{{ t("（加群验证答案 ") }}<code>jing_hy</code>{{ t("）；问题反馈请附诊断包与现象（维护 → 导出诊断包）。") }}</li>
          <li>{{ t("「说明」里还有路线、进游戏后的操作与「也可以让 AI 帮你修」，点窗口左下角「说明」查看。") }}</li>
        </ul>
      </Card>
    </section>
  </div>
</template>
