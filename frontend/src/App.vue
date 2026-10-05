<script setup>
import { ref, computed, onMounted } from "vue";
import {
  Library, Wrench, PackageCheck, Rocket, Settings, Info, Palette,
} from "lucide-vue-next";
import { store, refreshState, setTheme, THEMES, PAGE_IDS, onStateRefreshed } from "./store.js";
import { waitForBridge, reportFrontendError } from "./lib/bridge.js";
import { loadSettings } from "./lib/settings.js";
import { dragHasFiles, importDroppedFile } from "./lib/importMod.js";
import { normalizeAnnouncements } from "./lib/announce.js";
import UpdateBadge from "./components/UpdateBadge.vue";
import { showModalDialog, showToast } from "./lib/dialog.js";
import { call } from "./lib/bridge.js";
import DialogHost from "./components/DialogHost.vue";
import OnboardingTour from "./components/OnboardingTour.vue";
import CharacterPickerDialog from "./components/CharacterPickerDialog.vue";
import ToastHost from "./components/ToastHost.vue";
import AboutPage from "./pages/AboutPage.vue";
import SettingsPage from "./pages/SettingsPage.vue";
import AssistPage from "./pages/AssistPage.vue";
import DepsPage from "./pages/DepsPage.vue";
import LaunchPage from "./pages/LaunchPage.vue";
import ModLibraryPage from "./pages/ModLibraryPage.vue";
import UiPreviewPage from "./pages/UiPreviewPage.vue";

const pages = {
  preview: UiPreviewPage,
  library: ModLibraryPage, assist: AssistPage, dependencies: DepsPage, launch: LaunchPage, settings: SettingsPage,
  about: AboutPage,
};
const tabs = [
  { id: "library", name: "服装 Mod", icon: Library },
  { id: "assist", name: "辅助 Mod", icon: Wrench },
  { id: "dependencies", name: "依赖", icon: PackageCheck },
  { id: "launch", name: "启动", icon: Rocket },
  { id: "settings", name: "设置", icon: Settings },
  { id: "about", name: "说明", icon: Info },
];
const THEME_LABELS = { light: "浅色", dark: "深色", amber: "琥珀", cyan: "青蓝", violet: "紫罗兰", emerald: "翡翠" };
// ⚠️ 主题读 **store 的单一真源**（2026-10-04）：原先这里是 `ref(currentTheme())` 的本地副本，
// 于是"设置页改了主题、侧栏标签不跟着变"（两套真相）。现在两边都只认 `store.theme`。
const theme = computed(() => store.theme);
const themeLabel = computed(() => THEME_LABELS[theme.value] || theme.value);
// 版本号与更新入口统一在左侧栏的 UpdateBadge 里（顶栏不再显示，这里也就没有 versionText 了）
// 拖放导入：提示层**松开鼠标就消失**（用户要求「应该是释放就消失」），拖拽计数避免子元素抖动
const dragging = ref(false);
// ⚠️ 原来这里还有一个 `notices` 公告条 ref（以及模板里那块卡片）——公告改成**弹窗**之后
// 它再也没有被赋过值，属于死代码，2026-10-04 一并删除（见 `maybeShowAnnouncements`）。
let firstRunChecked = false;
const tourVisible = ref(false);   // 新手引导浮层（挖孔高亮 + 气泡）
let dragDepth = 0;

// ── 终末地异常退出的**弹窗**（用户 2026-10-03：「我需要崩溃的弹窗」）──────────
// 后端早就有现成的：`crash_bundle_status()` 返回 `{watch, fresh, latest}`，
// 其中 `fresh` 是 `crashwatch.take_bundle()` 的**"取走"语义** —— 一次调用就消费掉，
// 天然不会重复弹。但**前端从来没调用过它**，于是用户看到的是
// 「管理器好像捕捉不到终末地崩溃」：日志里明明写了
// `[crash] 已生成诊断包 reason=process_disappeared`、包也生成了，只是没人告诉他。
let crashTimer = null;
let crashPolling = false;
async function pollCrash() {
  if (crashPolling) return;
  // ⚠️ 没有 pywebview 桥时直接跳过（2026-10-04 修）：`#preview` / `?demo=1` / 直接
  // 用浏览器打开这个页面时没有桥，而 `call()` 内部会 `waitForBridge` **等满 15 秒**
  // 才抛错 —— 每 3 秒一次、每次挂 15 秒，预览页/截图环境控制台会持续刷错误。
  if (!(window.pywebview && window.pywebview.api)) return;
  crashPolling = true;
  try {
    const r = await call("crash_bundle_status");
    const fresh = r && r.fresh;
    // ── 连续启动失败 → 「强力修复」（用户 2026-10-05 要求）───────────────────
    // 用户原话：「**如果连续启动三次失败，加个弹窗，做个强力修复功能，一键还原终末地，
    //            然后清空依赖并重新下载**，注意：**还原终末地需要把其他第三方的也还原掉**」。
    // 判据在后端（`crashwatch.strong_repair_status`）：**崩了**或**静默闪退**都计数，
    // 连续 3 次、且这一档还没提示过时 `ready=true`。
    // ⚠️ 顺序是先 `mark_strong_repair_prompted` 再弹 —— 万一弹窗期间轮询又跑一轮，也不会重复弹。
    const sr = r && r.strong_repair;
    if (sr && sr.ready) {
      try { await call("mark_strong_repair_prompted"); } catch (e) { /* 忽略 */ }
      const repairChoice = await strongRepairModal(sr, !!fresh);
      if (repairChoice === "bundle") {
        // 用户想先看诊断包 → 继续往下走原来的崩溃包逻辑（不 return）
      } else {
        if (repairChoice) await forceRepair();
        return;
      }
    }
    if (fresh) {
      const path = String(fresh.path || fresh.bundle || "");
      const reason = String(fresh.reason || "process_disappeared");
      const mods = Array.isArray(fresh.mods) ? fresh.mods : [];
      // ⚠️⚠️ **C12：崩溃弹窗要把"接下来能做什么"给出来**（2026-10-03 补回归）。
      // 0.9.5 的 `showCrashModal`（`app.js:3429-3505`）会按 `cause.kind` 分支，
      // 展示**归因**与"收进包里的终末地日志清单"，并给「**去 Mod 库清理冲突**」+
      // 「**一键关闭其中一个（自行选择）**」两个按钮 → 直接接到 `ConflictDialog`。
      // 换代后这里只弹标题/路径/启用的 Mod，**"崩溃之后怎么处理"这条闭环断了** ——
      // 用户看到"崩了、包在这"，然后呢？还是得自己去库里猜是哪两个冲突。
      const cause = (fresh.cause && typeof fresh.cause === "object") ? fresh.cause : {};
      const kind = String(cause.kind || fresh.cause_kind || "");
      // ⚠️ **判据只认 `kind === "mod_conflict"`**（2026-10-04 修）。原先还看
      // `!!cause.conflict_group || !!cause.conflicts`，而后端 `gpu_compiler` 那条归因
      // **也带 conflicts 列表**（crashwatch 特意把"显卡编译器崩"与"Mod 冲突"分开，
      // 就是为了避免让用户白折腾去清 Mod）—— 多加这两个条件等于把它又合并回去了。
      const isConflict = kind === "mod_conflict";
      // 崩溃后的**建议动作**（用户 2026-10-05：「崩溃不要卸掉功能，应该弹窗建议清空依赖
      // 并重新下载重试」）。后端只在"崩在图形/注入链那层"时才给 advice（实测判据：
      // WER 故障模块 / DLSS5 插件自己的崩溃记录落在 dxgi / d3d11 / d3d12 / nvngx…），
      // 所以这里不自己判断"该不该重装"，只负责把它摆出来 + 给一个能点的按钮。
      const advice = (fresh.advice && typeof fresh.advice === "object") ? fresh.advice : {};
      const canRedownload = String(advice.action || "") === "reset_dependencies_and_redownload";
      const lines = [
        `游戏进程在启动后异常结束了（${reason}）。`,
        "",
      ];
      if (isConflict) {
        lines.push(
          "**看起来是 Mod 资源冲突**：同时启用的 Mod 改了同一批资源。",
          "",
          "可以点「去清理冲突」—— 会列出来让你选保留哪一个，不用自己猜。",
          "",
        );
      } else if (cause.detail || cause.reason) {
        lines.push(`归因：${cause.detail || cause.reason}`, "");
      }
      if (advice.message) {
        lines.push(String(advice.message), "");
      }
      lines.push(
        `管理器已经把现场收集成一个诊断包：`,
        path || "（路径读取失败）",
        "",
      );
      if (mods.length) lines.push(`当时启用的 Mod：`, `· ${mods.join("\n· ")}`, "");
      lines.push("把这个 zip 发到 Issues 或 QQ 群，就能定位原因。");
      const extraButtons = [];
      if (isConflict) extraButtons.push({ text: "去清理冲突", value: "conflict" });
      if (canRedownload) extraButtons.push({ text: "清空依赖并重新下载", value: "redownload" });
      const choice = await showModalDialog({
        title: isConflict ? "终末地异常退出（疑似 Mod 冲突）" : "终末地异常退出",
        message: lines.join("\n"),
        okText: "打开诊断包", cancelText: "知道了",
        // 冲突时多给一个"去清理"的按钮（0.9.5 的主路径）；
        // 崩在注入链时多给一个"清空依赖重下"的按钮（2026-10-05 加，见 `redownloadDependencies`）。
        extraButtons,
      });
      if (choice === "redownload") {
        await redownloadDependencies();
      } else if (choice === "conflict") {
        // 跳到 Mod 库并让那边自己把冲突窗弹出来（它读 `conflict_groups`）
        store.tab = "library";
        try {
          const info = await call("conflict_groups");
          const groups = (info && info.groups) || [];
          if (groups.length) showToast(`发现 ${groups.length} 组冲突，在「Mod 库」页里处理`, "warn");
          else showToast("当前没有检测到冲突组（可能是历史记录）", "info");
        } catch (e) { /* 忽略 */ }
      } else if (choice && path) {
        try { await call("open_path_in_explorer", path); } catch (e) { /* 忽略 */ }
      }
    }
  } catch (e) { /* 忽略轮询错误 */ } finally {
    crashPolling = false;
  }
}

// 「清空依赖并重新下载」——崩溃弹窗里的建议动作（用户 2026-10-05：
// 「**崩溃不要卸掉功能，应该弹窗建议清空依赖并重新下载重试**」）。
// 与设置页那个红按钮走**同一条后端路径**（`reset_dependencies_and_redownload`），
// 也照它一样：先确认（破坏性动作）→ 清空 → 跳依赖页自动开跑。
// ⚠️ 这里**不动任何插件开关**：用户的功能照旧开着，只是把整套组件重装一遍再试。
async function redownloadDependencies() {
  const ok = await showModalDialog({
    title: "清空依赖并重新下载",
    message: [
      "会依次做三件事：",
      "① 从备份区还原终末地本体（没做过净化就跳过）；",
      "② 清掉 runtime 与 assets，然后重新下载并展开；",
      "③ 跳到「依赖」页开始一键下载。",
      "",
      "你的 Mod 库、Mod 备份与路径设置都不受影响。",
      "清完到装好之间，组件列表会先变空，属于正常现象。",
    ].join("\n"),
    okText: "清空并重新下载",
    cancelText: "取消，什么都不做",
    focusCancel: true,
  });
  if (!ok) return;
  let result = null;
  try {
    result = await call("reset_dependencies_and_redownload");
  } catch (e) { /* call 已经弹过错误窗了 */ }
  if (!result || result.ok === false) {
    showToast((result && result.message) || "清空失败，详情见运行日志", "danger");
    return;
  }
  showToast("已清空 runtime 与 assets，正在跳到依赖页重新下载…", "success");
  store.autoStartDeps = true;
  store.tab = "dependencies";
}

// 「连续启动失败」的说明窗（用户 2026-10-05 要求）。
// 返回值：主按钮 → truthy（去修）；`"bundle"` → 用户想先看诊断包；取消 → falsy。
async function strongRepairModal(sr, hasBundle) {
  const lines = [
    `终末地已经**连续 ${sr.streak} 次**启动失败了（每次启动后很快就退出）。`,
    "",
    "这种时候多半不是某个开关没开对，而是组件本身坏了、或者被第三方文件搅了。",
    "「强力修复」会依次做两件事：",
    "",
    "① **还原终末地**：把游戏目录里的第三方注入**全部**搬走（**不管是谁装的** —— 别的工具、" +
      "整合包残留都算），并把系统原版文件补回去，游戏目录回到纯原版；",
    "② **清空依赖并重新下载**：runtime 与 assets 整个重装一遍。",
    "",
    "你的 Mod 库、Mod 备份与路径设置都不受影响；被搬走的第三方文件会留备份，" +
      "设置页的「撤销清除」可以原样放回。",
    "重下要花点时间（国内建议先把加速器打开）。",
  ];
  const extraButtons = [];
  if (hasBundle) extraButtons.push({ text: "先看诊断包", value: "bundle" });
  return await showModalDialog({
    title: "连续启动失败 —— 建议强力修复",
    message: lines.join("\n"),
    okText: "强力修复",
    cancelText: "暂时不要",
    focusCancel: true,
    extraButtons,
  });
}

// 「强力修复」本体：与后端 `force_repair` 一一对应（还原终末地含第三方 → 清空依赖重下）。
// 破坏性动作 ⇒ **二次确认 + 默认聚焦取消**（用户定的规矩）。
async function forceRepair() {
  const ok = await showModalDialog({
    title: "强力修复",
    message: [
      "会依次做两件事：",
      "① 还原终末地：把游戏目录里的第三方注入全部搬走（不管是谁装的），" +
        "并把系统原版文件补回去；",
      "② 清空 runtime 与 assets，然后重新下载并展开（接着会自动跳到「依赖」页开跑）。",
      "",
      "被搬走的第三方文件会留备份，设置页「撤销清除」可以原样放回。",
      "游戏正在运行时请先完全退出游戏 —— 否则这一步会被拒绝。",
    ].join("\n"),
    okText: "开始强力修复",
    cancelText: "取消，什么都不做",
    focusCancel: true,
  });
  if (!ok) return;
  let result = null;
  try {
    result = await call("force_repair");
  } catch (e) { /* call 已经弹过错误窗了 */ }
  if (!result || result.ok === false) {
    showToast((result && result.message) || "强力修复失败，详情见运行日志", "danger");
    return;
  }
  showToast(result.message || "强力修复完成，正在跳到依赖页重新下载…", "success");
  store.autoStartDeps = true;
  store.tab = "dependencies";
}

// 公告消费（**幂等**）：后端公告由后台线程拉取，且要等首屏就绪（最多 15 秒）才请求，
// 所以"启动那一刻读一次"必然读到空 —— 这正是 2026-09-30 记录、2026-10-03 仍然存在的 bug
// （用户：「公告好像没出来」）。定式：做成幂等函数、挂在数据刷新点上，再留启动后定时兜底。
const shownNoticeKeys = new Set();
// ⚠️ 关键：**先重新拉一次 state 再消费**。`store.state` 只是"上一次 get_state 的快照"，
// 而公告是后端**后台线程**稍后才填进去的（实测：启动 13:50:28 拉 state 时还是空的，
// 13:50:32 后端才拿到 1 条）—— 只重读本地快照的话，永远读的是那份空数据。
// 用户 2026-10-03 连续两轮反馈「还是没弹」，根因就在这里。
function refreshThenShowAnnouncements() {
  // **不要 await**：刷新失败或悬挂时，消费必须照常跑（用当前快照试一次）。
  // 反过来也一样 —— 消费（可能弹窗）绝不阻塞状态刷新。
  refreshState().catch(() => {}).finally(() => { maybeShowAnnouncements(); });
  maybeShowAnnouncements();       // 先用现有快照试一次，立即执行
}

async function maybeShowAnnouncements() {
  const list = normalizeAnnouncements(store.state && store.state.announcements);
  const fresh = list.filter((n) => !shownNoticeKeys.has(n.key));
  if (!fresh.length) return;
  fresh.forEach((n) => shownNoticeKeys.add(n.key));

  // ⚠️ 2026-10-03 用户点破：公告要的是**弹窗**，不是顶部那条卡片。
  // （`alerts.json` 自己的说明就写着「管理器启动后**弹**一次、看完即记已读」——一直是弹窗语义，
  //  是我把它实现成了顶部公告条，于是用户连着几轮说"没弹"，我却在一直查"数据没到"。）
  // 多条公告**逐条弹**，一条一个框（用户定的规矩：一个弹窗只做一件事）。
  for (const item of fresh) {
    try {
      await showModalDialog({
        title: item.title || "公告",
        message: item.body || "",
        okText: "知道了",
        showCancel: false,
        link: item.link ? { url: item.link, text: item.link } : null,
      });
    } catch (e) { /* 弹窗失败不该影响启动 */ }
  }
  // 提示里若还有 URL，交给系统浏览器打开（与"能点的网址不另外配按钮"一致）
  try {
    // 记已读：下次启动不再弹（后端会把这些 id 从公告列表里摘掉）
    await call("announcements_seen", fresh.map((n) => n.key));
  } catch (e) { /* 记不上也不影响本次显示 */ }
}

// 打开外部链接（弹窗里的网址点了直接开，与"能点的网址不另外配按钮"一致）
// 打开外部链接（弹窗里的网址点了直接开，与"能点的网址不另外配按钮"一致）
// ⚠️ 这里是**唯一实现**（2026-10-04）：`lib/util.js` 里那份 `openExternal` 已删 ——
// 它直接调 `window.pywebview.api`，绕过了 `call()` 的"失败弹窗 + 桥未就绪重试"。
async function openExternal(url) {
  if (!url) return;
  try { await call("open_external", String(url)); } catch (e) { /* call 已弹窗 */ }
}

async function onDrop(event) {
  event.preventDefault();
  dragDepth = 0;
  dragging.value = false;
  const files = Array.from((event.dataTransfer && event.dataTransfer.files) || []);
  for (const file of files) {
    await importDroppedFile(file, {
      onDone: async () => {
        await refreshState();
        loadSettings();
      },
      // ⚠️ **B12**：导入后立刻让「角色归属待确认」那张表刷新一次 ——
      // 认不出角色的包会**当场弹选择窗**，而不是留一句"你稍后自己去改"。
      onNeedConfirm: async () => { pickerRef.value?.reload?.(); },
    });
  }
}
// 角色归属待确认弹窗的引用（导入 Mod 后要主动刷新它）
const pickerRef = ref(null);
const themeOpen = ref(false);
const currentPage = computed(() => pages[store.tab]);
const currentName = computed(() => tabs.find((t) => t.id === store.tab)?.name || "");

// 切页签要**写回** config.last_tab —— 之前只有启动时读、从不保存，"记住上次页签"实际不成立。
// ── 下载中关窗口的确认（后端 `app.py::_on_closing` 会调 `window.mcAskExit()`）──────
// ⚠️ **2026-10-03 补上**：后端那条链路早就写好了（有活跃下载时取消关闭、并执行
// `window.mcAskExit && window.mcAskExit()`），但**前端从来没有定义它** ——
// 于是用户点关闭时：什么也不弹、窗口也关不掉（现象就是"卡死、也没出弹窗"）。
// 这里按后端约定实现：弹确认框；选「仍然退出」→ 调 `confirm_exit()` 让后端放行，
// 然后再关一次窗；选「继续下载」→ 什么都不做（窗口保持打开）。
window.mcAskExit = async function () {
  try {
    const ok = await showModalDialog({
      title: "还在下载，确定要退出吗？",
      message:
        "现在退出会**中断正在进行的下载**（已下完的部分会保留，下次可以继续）。\n\n" +
        "想让它跑完的话，选「继续下载」就行。",
      okText: "仍然退出", cancelText: "继续下载",
    });
    if (!ok) return;
    // ⚠️ 这里**只调后端**，不要再调 JS 的 `window.close()` ——
    // 那个 `window` 是浏览器的 window，关不掉 pywebview 的窗口（还会让人以为"关过了"）。
    // 后端 `confirm_exit` 会自己收尾并 `os._exit`，这条调用不返回是正常的。
    try { await call("confirm_exit"); } catch (e) { /* 后端已经在退出了，忽略即可 */ }
  } catch (e) { /* 弹窗都失败了就别再挡着，交给后端超时放行 */ }
};

async function goTab(id) {
  const changed = store.tab !== id;
  store.tab = id;
  // ⚠️ **切页要回到顶部**（2026-10-03 用户：「换页不应该保留滑动的位置，应该到最上」）。
  // 滚动发生在**页面里的滚动容器**上（不是 window），所以两处都要复位：
  //   ① 主内容区 `#main-scroll`（各页共享的那个滚动容器）；
  //   ② window / documentElement（兜底，防止某些页自己滚 window）。
  // 用 `nextTick` 之外的微任务时机：先滚，再渲染新页，避免"先渲染出新页再跳动"。
  if (changed) {
    const reset = () => {
      const el = document.getElementById("main-scroll");
      if (el) el.scrollTop = 0;
      try { window.scrollTo({ top: 0, behavior: "auto" }); } catch (e) { window.scrollTo(0, 0); }
      if (document.documentElement) document.documentElement.scrollTop = 0;
      if (document.body) document.body.scrollTop = 0;
    };
    reset();
    requestAnimationFrame(reset);      // 新页挂载后可能又设了一次滚动位置，再复位一遍
  }
  try { await call("save_config", { last_tab: id }); } catch (e) { /* 记不上不影响使用 */ }
}

// 主题切换：走 store 的唯一入口（它会写 localStorage + store.theme + config.json）
async function pickTheme(name) {
  await setTheme(name);
  themeOpen.value = false;
}

onMounted(async () => {
  // UI 预览页（#preview?d=xxx）：只截图/回归用，不碰后端
  if (String(location.hash || "").startsWith("#preview")) {
    store.tab = "preview";
    return;
  }
  // `?demo=1`：用真实库快照渲染 —— **只在 `VITE_UI_DEMO=1 npm run build` 的构建里存在**。
  // 正式构建会被下面这行 `import.meta.env.VITE_UI_DEMO` 判断整段摇掉（rollup 常量折叠），
  // 所以正式包既没有这段逻辑、也不会去读任何本地文件（用户准则：正式版不含测试通道）。
  if (import.meta.env.VITE_UI_DEMO === "1"
      && new URLSearchParams(location.search).get("demo") === "1") {
    await new Promise((resolve) => {
      const el = document.createElement("script");
      el.src = "./demo-state.js";
      el.onload = resolve;
      el.onerror = resolve;
      document.head.appendChild(el);
    });
    if (window.__DEMO_STATE__) {
      store.state = window.__DEMO_STATE__;
      // ⚠️ 不再往 `store.mods` 写一份（2026-10-04：那个字段只写不读，页面统一读 `store.state.mods`）
      // 快照里预置的封面（data URI）——file:// 下前端拿不到本地图片，只能内联
      store.demoCovers = window.__DEMO_STATE__.demo_covers || {};
      store.demoPending = window.__DEMO_STATE__.demoPending || null;
      store.config = store.state.config || {};
      store.ready = true;
      loadSettings();
      // demo 模式也要能看引导：快照里把 first_run.onboarding_done 置 false 即可复现首启
      const demoFr = store.state.first_run || {};
      if (demoFr.first_run && !demoFr.onboarding_done) tourVisible.value = true;
      // demo 模式走一遍公告消费（否则快照里给了公告也看不到，等于没法验证这条链路）
      await maybeShowAnnouncements();
      // 调试用：模拟"公告迟到" —— 后端后台线程稍后才填进去，看兜底定时器能不能补上。
      // 只在 `?demo=late` 时启用，正式包不含这段（整个 VITE_UI_DEMO 分支都会被摇掉）。
      if (new URLSearchParams(location.search).get("demo") === "late") {
        setTimeout(() => {
          store.state.announcements = [{
            id: "late-arrival", level: "info",
            title: "迟到公告：兜底轮询把它补上了",
            body: "这条是在界面起来之后才塞进 state 的，用来验证兜底是否有效。",
          }];
        }, 3000);
      }
      return;
    }
  }
  // 拖放导入（全局：任何页都能拖）
  window.addEventListener("dragenter", (e) => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();
    dragDepth += 1;
    dragging.value = true;
  });
  window.addEventListener("dragover", (e) => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();                       // 不 preventDefault 就不会派发 drop
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
  });
  window.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) dragging.value = false;
  });
  window.addEventListener("drop", onDrop);
  window.addEventListener("error", (e) => reportFrontendError("window.error", e.message || ""));
  window.addEventListener("unhandledrejection", (e) =>
    reportFrontendError("unhandledrejection", String((e.reason && e.reason.message) || e.reason)));
  // 桥没就绪时等一会儿（旧版有 pywebviewready + DOMContentLoaded 两道兜底，这里等价处理）
  // ⚠️ 2026-10-03：**要等到具体方法就绪**，不能只看"api 对象在不在"。
  // pywebview 的 `api` 对象先出现、方法随后逐个注入 —— 原来只等"api 对象在"，
  // 于是紧跟其后的 `call("ui_ready")` 撞上"api 在、方法还没挂上"的窗口期，
  // 抛 `api[e] is not a function`（用户截图反馈的那条红框）。
  // 现在等的是 boot 真正要用的第一个方法 `ui_ready` 出现为止。
  if (await waitForBridge(15000, "ui_ready")) {
    // 告诉后端"界面已经起来了" —— `_warm_up` 第一件事就是等这个信号（最多 15 秒），
    // 等不到它就会白等满 15 秒才开始拉公告/角色表。前端此前**从没调用过**它（grep 无结果），
    // 所以公告要等 15 秒后才可能到。这里一进 boot 就先发信号。
    try { await call("ui_ready"); } catch (e) { /* 不支持也不影响 */ }
    try {
      await refreshState();
      // ⚠️ 必须把 config 灌进 settings —— 否则所有设置项/开关都显示成空（2026-10-02 实测：
      // 注入开关全显示"关"，因为 settings 从没被填充过）。
      loadSettings();
      // 旧版会记住上次停留的页签（config.last_tab）；带 hash 深链时以 hash 为准
      // 校验后再用：配置里残留的旧页签名会让 currentPage 变成 undefined、页面一片空白
      const lastTab = store.state.config && store.state.config.last_tab;
      if (!location.hash && PAGE_IDS.includes(lastTab)) store.tab = lastTab;
      await maybeShowAnnouncements();
      // 首次启动：**只提示一次**（判据用后端持久化的 onboarding_done，而不是"当前还没就绪"
      // 这类会一直为真的状态 —— 否则会连环弹）。
      const fr = store.state.first_run || {};
      if (!firstRunChecked && fr.first_run && !fr.onboarding_done) {
        firstRunChecked = true;
        // 用户 2026-10-03：「现在首次使用引导变成只有文字的了，我需要那种一个箭头指向按钮的
        // 那种」—— 原来那个纯文字弹窗是评审建议下改的，但他要的是**高亮 + 箭头指向**的
        // 分步引导（0.4.0 那版就是分步 tour，本次移植回来并补上箭头）。
        tourVisible.value = true;
      }
    } catch (e) { /* call() 已经弹过窗 */ }
  }
});

// 引导步骤（沿用 0.4.0 的四步，内容按现在的界面更新；
// 第二步按用户要求补上"也可以直接下载"这条路）。
const TOUR_STEPS = [
  {
    tab: "dependencies", target: "dep-update-all-btn",
    title: "第一步：先把组件装齐",
    body: "这里是「依赖」页。点这个「安装缺失依赖」按钮，程序会自动下载并安装\n"
      + "XXMI Launcher、XXMI 库、EFMI、DLSS5 组件等全部依赖（需要联网）。\n\n"
      + "建议先点它，等装完再去启动。右边那个黑框会显示下载线路与进度。",
  },
  {
    tab: "library", target: "mod-download-box",
    title: "第二步：把 Mod 弄进来",
    body: "有两种方式：\n"
      + "① 把 Mod 的 .zip / .7z / .rar 拖到窗口任意位置 —— 松手后自动解压进库并识别角色；\n"
      + "② 直接下载：在「下载 Mod」里粘贴网址（一行一个），也支持香蕉网页面地址，\n"
      + "   会自动取真实文件直链、并带出封面。\n\n"
      + "同一个角色默认只保留一个 Mod（自动互斥），避免游戏崩。",
  },
  {
    tab: "launch", target: "oneclick-launch-btn",
    title: "第三步：一键启动",
    body: "点这个「一键启动」：程序会补齐缺失组件、同步注入库、跑一遍初始化自检，\n"
      + "然后拉起 XXMI Launcher（不会自动进游戏，进游戏在 XXMI 里点 Start）。\n\n"
      + "第一次可能会提示「请再点一次一键启动」，看到后再点一次即可。",
  },
  {
    tab: "settings", target: "game-restore-btn",
    title: "第四步：随时可以还原",
    body: "「设置」页有「还原游戏本体」：\n"
      + "本程序对游戏目录做的任何改动都可回滚（净化前会完整备份、只移动不删除）。\n\n"
      + "同一页还有「依赖清空并重新下载」——组件装坏了、缺文件时可以一键清空重来。",
  },
];

async function finishTour() {
  tourVisible.value = false;
  try { await call("save_config", { onboarding_done: true }); } catch (e) { /* 记不上也不影响本次 */ }
}

// 挂在"每次状态刷新之后"（切页、改设置、下载进度刷新……都会触发），
// 这样公告一到就能补上；再留几个延迟兜底，覆盖"后台线程 15 秒内才拉到"的情况。
onStateRefreshed(() => { maybeShowAnnouncements(); });

// 崩溃轮询：常驻但很轻（一次 get_state 级别的小调用）。游戏异常退出后
// 后端会自动收集现场并放进 `fresh`，这里取到就弹窗。
crashTimer = setInterval(pollCrash, 3000);
// ⚠️ 这两个兜底 setTimeout **也要登记**（2026-10-04 修）：它们原先没进 `announceTimers`，
// 而下面 `clearAnnounceTimers()` 只清登记过的 —— 用户正好在 4~10 秒窗口内关窗口时，
// pywebview 会等这两个回调跑完（与历史上"关程序卡死"同源）。
const crashKickTimers = [];
[4000, 10000].forEach((d) => crashKickTimers.push(setTimeout(pollCrash, d)));
// 启动后的一段时间里**每 5 秒轮询一次**：公告是后端后台线程稍后才填进去的
// （实测启动后约 4 秒到），具体到几点不确定，所以用轮询兜住，而不是猜几个时刻。
// 60 秒后自然停下，不做常驻轮询。消费一旦成功，`shownNoticeKeys` 会去重，不会重复弹。
// ⚠️ 这些定时器**必须在窗口关闭时清掉**：App.vue 是根组件、永远不会 unmount，
// 而 pywebview(WebView2) 关闭时要等 JS 把未完成的定时器跑完 —— 之前那个 60 秒轮询
// 就导致**关程序时卡死**（用户 2026-10-03 反馈「mod 管理器现在又关闭时卡死」）。
// 轮询本身也收紧：8 次 × 3 秒 = 24 秒足够（实测公告启动后约 4 秒就到）。
const announceTimers = [];
let announceTicks = 0;
announceTimers.push(setInterval(() => {
  announceTicks += 1;
  refreshThenShowAnnouncements();
  if (announceTicks >= 8) { clearInterval(announceTimers[0]); }
}, 3000));
[1200, 2500, 5000].forEach((delay) => {
  announceTimers.push(setTimeout(() => { refreshThenShowAnnouncements(); }, delay));
});

// 关窗/刷新时一律清干净，绝不拖住退出流程
function clearAnnounceTimers() {
  if (crashTimer) { clearInterval(crashTimer); crashTimer = null; }
  crashKickTimers.forEach((t) => clearTimeout(t));
  crashKickTimers.length = 0;
  announceTimers.forEach((t) => { clearInterval(t); clearTimeout(t); });
  announceTimers.length = 0;
}
window.addEventListener("beforeunload", clearAnnounceTimers);
window.addEventListener("pagehide", clearAnnounceTimers);
</script>

<template>
  <div class="flex h-full">
    <aside class="w-52 shrink-0 flex flex-col border-r" style="background: var(--surface); border-color: var(--border)">
      <div class="h-12 px-4 flex items-center text-sm font-semibold border-b" style="border-color: var(--border)">
        终末地 Mod 管理器
      </div>
      <nav class="flex-1 p-2 space-y-0.5">
        <button v-for="t in tabs" :key="t.id" @click="goTab(t.id)"
          class="w-full flex items-center gap-2.5 px-3 py-2 rounded text-left transition-colors"
          :style="store.tab === t.id
            ? { background: 'var(--accent-soft)', color: 'var(--accent)', fontWeight: 500 }
            : { color: 'var(--text-muted)' }">
          <component :is="t.icon" :size="16" />
          <span class="text-sm">{{ t.name }}</span>
        </button>
      </nav>
      <!-- 自更新入口（用户要求：左侧导航下面、主题色上面） -->
      <div class="p-1.5 border-t" style="border-color: var(--border)">
        <UpdateBadge />
      </div>
      <div class="p-2 border-t relative" style="border-color: var(--border)">
        <button @click="themeOpen = !themeOpen"
          class="w-full flex items-center gap-2.5 px-3 py-2 rounded text-sm"
          style="color: var(--text-muted)">
          <Palette :size="16" />
          <span>主题：{{ themeLabel }}</span>
        </button>
        <div v-if="themeOpen" class="absolute bottom-12 left-2 right-2 card p-1.5 shadow-lg z-20">
          <button v-for="t in THEMES" :key="t" @click="pickTheme(t)"
            class="w-full text-left px-2.5 py-1.5 rounded text-sm"
            :style="t === theme ? { background: 'var(--accent-soft)', color: 'var(--accent)' } : {}">
            {{ THEME_LABELS[t] }}
          </button>
        </div>
      </div>
    </aside>

    <main id="main-scroll" class="flex-1 min-w-0 overflow-auto">
      <!-- ⚠️ 2026-10-04 删掉「公告条」这一块：公告改成**弹窗**之后（用户点破
           「公告要的是弹窗，不是顶部那条卡片」），`notices` 再也没有被赋过值 ——
           模板留着也不会渲染，但它内部那个 `<a :href>` 是**唯一没走 open_external** 的
           远端链接（真被填上时点击行为与其他链接不一致）。死代码连同 `dismissNotices`
           一起删除。 -->
      <header class="h-14 px-6 flex items-center justify-between border-b sticky top-0 z-10"
              style="background: var(--surface); border-color: var(--border)">
        <div>
          <h1 class="page-title">{{ currentName }}</h1>
        </div>
        <!-- 版本号与更新入口统一放在左侧栏底部（顶栏不再重复显示） -->
      </header>
      <div class="px-6 py-5">
        <div class="page-inner">
          <component :is="currentPage" v-if="currentPage" />
          <div v-else class="card p-6 text-sm" style="color: var(--text-muted)">
            「{{ currentName }}」还在迁移中（新前端逐页搬，这一页暂时用旧界面）。
          </div>
        </div>
      </div>
    </main>

    <!-- 拖放提示层：松手即消失，职责只是"告诉你松手就能导入" -->
    <div v-if="dragging" class="fixed inset-0 z-[70] flex items-center justify-center"
         style="background: rgba(0,0,0,.35)">
      <div class="card px-6 py-4 text-center shadow-lg">
        <div class="font-medium">松手即可导入 Mod</div>
        <div class="text-xs mt-1" style="color: var(--text-muted)">支持 .zip / .7z / .rar（进度显示在顶部提示条）</div>
      </div>
    </div>

    <!-- 角色归属待确认：预识别不确定时让用户选（识别错会让同角色互斥失效） -->
    <CharacterPickerDialog ref="pickerRef" />

    <!-- 新手引导：挖孔高亮 + 气泡 -->
    <OnboardingTour v-model="tourVisible" :steps="TOUR_STEPS" @finish="finishTour" />

    <!-- ⚠️ 必须接 `open-link`：DialogHost 会 emit 它，但这里以前是裸的 `<DialogHost />`
         ⇒ 弹窗/公告里的链接**点了没有任何反应**（用户定的规矩是"点击网址直接打开"）。 -->
    <DialogHost @open-link="(url) => openExternal(url)" />
    <ToastHost />
  </div>
</template>




