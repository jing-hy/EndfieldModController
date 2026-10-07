<script setup>
// 启动页（旧 #tab-launch）：一键启动 + 六个注入开关（**与设置页共享同一份 settings 状态**）。
import { ref, computed, onMounted, onUnmounted } from "vue";
import { call } from "../lib/bridge.js";
// ⚠️ 这里**必须把用到的都列全**（2026-10-04 修）：原先只导入了 showModalDialog / showAlert，
// 而「检查/修复完整性」那条链路用了 showProgressToast(313) / showToast(327) /
// hideProgressToast(329) —— 三个都不在作用域里 ⇒ 一点「修复」就在 try 之前抛
// ReferenceError，**自动修复分支根本不执行**（与历史上 `modDownloadFinished is not defined`
// 那次静默退化同型：控制台只报一句，界面上看起来只是"操作没做成"）。
import {
  showModalDialog, showAlert, showToast, showProgressToast, hideProgressToast,
} from "../lib/dialog.js";
import { refreshState } from "../store.js";
import { loadSettings } from "../lib/settings.js";
import { useLogAutoScroll } from "../lib/autoscroll.js";
import { settings, saveSetting, syncConfig } from "../lib/settings.js";
import { promptVcRuntimeInstall } from "../lib/vcRuntime.js";
import { store } from "../store.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Switch from "../components/ui/Switch.vue";

const consoleLog = ref("就绪。点「一键启动」：先跑初始化自检（缺什么补什么），再拉起 XXMI Launcher。");
const renderApi = ref("");
// ⚠️ **渲染 API 的告警文案**（2026-10-03 补回归）。0.9.5 是这么写的：
//   vulkan / d3d12 → 「上次启动：X（**服装 Mod 不生效**，请在启动器里点 DirectX 11 启动）」
//   d3d11          → 「上次启动：DirectX 11」
//   其它           → 「上次启动：未知」
// 换代后只显示裸值（`vulkan` / `d3d11`），用户看到 "vulkan" 根本不知道**服装 Mod 不会生效** ——
// 而这是"我装了 Mod 怎么没效果"最常见的原因。
const renderApiText = computed(() => {
  const v = String(renderApi.value || "").toLowerCase();
  if (v === "vulkan") return "上次启动：Vulkan —— 服装 Mod 不生效，请在启动器里选 DirectX 11 启动";
  if (v === "d3d12") return "上次启动：DirectX 12 —— 服装 Mod 不生效，请在启动器里选 DirectX 11 启动";
  if (v === "d3d11") return "上次启动：DirectX 11";
  return "上次启动：未知（还没启动过，或读不到渲染 API）";
});
const renderApiWarn = computed(() => {
  const v = String(renderApi.value || "").toLowerCase();
  return v === "vulkan" || v === "d3d12";
});
const running = ref(false);

// ── 热重载（2026-10-04 用户要求）──────────────────────────────────────────────
// 用户原话：「加一个热重载，如果终末地在运行，现在一键启动那个位置左右切成两个按钮，
// 左边一键启动，右边热重载，点了热重载能包括改配置按 f10 等等，然后在终末地没运行的
// 时候就像现在这样整个按钮横在那」。
// 这里只负责"游戏当前在不在跑"（决定按钮布局）；真正做事的后端是 `api.hot_reload()`
// —— 改配置复用 `prepare_launch()`，再发 F10 让 3DMigoto 重新加载配置 / 重扫 Mod。
const gameLive = ref(false);
const hotReloading = ref(false);

// ★ **启动进度文案**（2026-10-07 用户要求："启动到扫除mod还是很慢，要是要时间就显示加载页面"）。
//   后端在启动链的关键节点写 `launch_stage`（检查注入库 → 随包组件 → 重建 Mod 目录 →
//   ReShade/面板 → 拉起 XXMI），前端本来就按 1~2 秒轮询 `get_state()`，直接读它显示即可。
//   读不到就是空串 —— 模板里 `v-if` 会把它整个藏起来，不会留空占位。
const launchStageText = computed(() => {
  const stage = store.state.launch_stage;
  return (stage && stage.text) || "";
});let liveTimer = null;

async function refreshGameLive() {
  try {
    const g = await call("game_running");
    gameLive.value = !!(g && g.running);
  } catch (e) { /* 查询失败就保持原状态，不能因为一次失败把按钮弹回去 */ }
}

async function hotReload() {
  if (hotReloading.value) return;          // 一次点击 = 一次热重载，连点不叠
  hotReloading.value = true;
  appendLog("热重载：先重铺配置，再给游戏发 F10…");
  startLogPolling();
  try {
    const r = await call("hot_reload");
    const msg = (r && r.message) || "热重载已发起";
    appendLog(msg);
    if (r && r.ok === false) {
      await showModalDialog({ title: "热重载没成功", message: String(msg) });
    }
  } catch (e) {
    appendLog("热重载失败：" + String(e));
  } finally {
    hotReloading.value = false;
    refreshGameLive();
  }
}

// ⚠️ **B8 / B9：开关要"真的有用"**（2026-10-03 补回归）。
// 用户定过：「那些**滑块要真的有用，不要就做表面功夫**，你确定一下」。
// 0.9.5 里这两个开关**拨动即装卸**：
//   * 乳摇（SecondaryMotion）：`secondary_motion_install` / `secondary_motion_uninstall`
//     + `secondary_motion_status` 报告「已就位 / 未注入 | plugin\sbm.dll 在/不在」；
//   * Poser：开启时 `poser_install`（补安装包 + 写游戏目录文件）+ `poser_status` 报告
//     「plugin\poser.dll 已就位 | loader XX 版 | 表情校准 N 份」。
// 换代后乳摇那个**连 apply 都没有**（只 `saveSetting` 写了个配置值），Poser 的 apply
// 只调 `set_poser_enabled`（仅重命名 dll、**不装机**）—— 后端那 5 个方法前端零调用。
// 结果就是"拨了开关看着变了、实际什么都没装"，正是用户最反感的表面功夫。
//
// ⚠️ 2026-10-03 第二修：这两个 apply 当时**只装卸、不写配置**，配置键一直是 true ⇒
// 界面弹回「已开启」+ 下次一键启动照旧注入（用户原话：「这两个按钮关不掉」）。
// 现在后端在这三个接口里统一落 `secondary_motion_injection` / `poser_injection`
// （`api._persist_injection_switch`），开关状态与"下次启动要不要注入"永远一致。
const SWITCHES = [
  // ★ 统一管理器（2026-10-06 用户定名与语义：「那个开关就要叫统一管理器，不要讲那么多，
  //   默认开，如果这个不开，锁快捷键强制关，如果开锁快捷键，这个强制开」）。
  { k: "minimal_injection", name: "统一管理器", desc: "注入 ReShade 与统一管理器面板",
    apply: (v) => call("set_minimal_injection", v) },
  { k: "dlss5_addon_enabled", name: "DLSS5 神经渲染", desc: "把游戏自身的 DLSS 输出替换成 DLSS5 神经渲染",
    apply: (v) => call("set_component_addon", "dlss5", v) },
  { k: "firstperson_addon_enabled", name: "第一人称视角", desc: "进游戏按 F1 切换第一人称",
    apply: (v) => call("set_component_addon", "firstperson", v) },
  // ★ DLSS4 多帧生成解锁（2026-10-06 用户要求："单列开关，与 dlss5 互斥，
  //   50 系和其他用不了的锁，默认关"；随后又要求"**说明要跟随显卡改变**"）。
  //   · **能不能用由后端判据决定**（`mfg_unlock_available`），不满足时这一行**禁用**并显示原因；
  //   · **与 DLSS5 互斥**：后端在开关入口与保存配置两处都会自动关掉另一个，这里如实提示；
  //   · ★ **说明跟随本机显卡**：后端的 `mfg_unlock_reason` 本来就是按显卡生成的
  //     （40 系 = "被挡在 2x 是软件白名单造成的，解锁后可开 3x/4x"；
  //      50 系 = "本身就有官方多帧生成，解锁提升不大"）—— 所以**别再写死"40 系"**，
  //     否则 50 系解锁之后显示的就是错的那句（这正是用户提的"说明要跟随显卡"）。
  { k: "mfg_unlock_enabled", name: "DLSS4 多帧生成",
    desc: () => store.state.component_addon_status?.config?.mfg_unlock_reason
      || "把多帧生成从 2x 解锁到更高倍率（与 DLSS5 神经渲染互斥，同时只能开一个）",
    apply: (v) => call("set_component_addon", "mfg", v),
    // ⚠️ 能不能用**不在 `settings` 里**（`settings` = `store.state.config` = AppConfig 的字段），
    //    而在 `store.state.component_addon_status.config`。2026-10-06：我第一版用 settings 读，
    //    恒为 undefined ⇒ 那一行**对所有人都灰**（40 系也一样"开不了"）。
    locked: () => !(store.state.component_addon_status?.config?.mfg_unlock_available),
    lockReason: () => store.state.component_addon_status?.config?.mfg_unlock_reason
      || "这台机器用不了这个功能" },
  { k: "efmi_injection", name: "皮肤 Mod", desc: "EFMI 服装 Mod 注入（关掉后不加载任何皮肤）" },
  { k: "secondary_motion_injection", name: "ShakingBreastManager", desc: "乳摇物理效果",
    // 拨动即装卸（不止写配置）：开启走 `secondary_motion_install`（装 proxy + plugin\sbm.dll
    // + 数据文件），关闭走 `secondary_motion_uninstall`。
    apply: (v) => call(v ? "secondary_motion_install" : "secondary_motion_uninstall") },
  { k: "poser_injection", name: "Endfield Poser", desc: "摆姿 / MMD 播放",
    // ⚠️ **首次开启要先装机**（`poser_install` 补安装包 + 写游戏目录文件），
    // 装好之后再翻 `set_poser_enabled` 这个"开关 dll"的动作 —— 0.9.5 就是这个顺序。
    apply: async (v) => {
      if (v) {
        const inst = await call("poser_install");
        if (inst && inst.ok === false) return inst;      // 装机失败就别翻开关了
      }
      return call("set_poser_enabled", v);
    } },
  { k: "hotkey_takeover", name: "Mod 快捷键锁定", desc: "把 Mod 自带快捷键锁成内部键，避免 Mod 之间抢键",
    apply: (v) => call("set_hotkey_takeover", v) },
];

// 切换一个开关：有专用接口的走专用接口（它们还要动文件/注入库），其余只写配置。
//
// ⚠️ 2026-10-03 修「乳摇 / Poser 这两个开关**关不掉**」（用户实测：点一下界面弹回「已开启」）：
//   ① 这两个走 `apply`，动作**真的做了**（日志里有"卸载乳摇注入/已停用 Poser"），但
//      `secondary_motion_injection` / `poser_injection` 没跟着写 —— 而后端是**按配置**
//      决定下次启动要不要注入的，前端 `loadSettings()` 又是从配置整份重灌的，于是
//      动作做了、界面弹回、下次一键启动照样装回来。现在后端会在动作成功后落配置并
//      回传 `{config: {键: 值}}`，这里照它回显（`syncConfig` 同步进 store，防止被下一次
//      `refreshState()+loadSettings()` 覆盖）。
//   ② 装卸要动游戏目录里的文件，一次点击要跑几百毫秒到几秒；**处理期间再点一下就变成
//      "关了又开"**（日志里能看到同一秒内 uninstall 和 install 交替）。加一把互斥锁。
const pendingSwitches = new Set();
function swText(sw) {
  // ★ 开关的说明文字：**允许写成函数**（2026-10-06 用户要求"DLSS4 的说明要跟随显卡改变"）
  //    —— 例如 DLSS4 那条要显示后端按本机显卡生成的理由（40 系 = 解锁到 3x/4x；
  //    50 系 = 提升不大），写死一句"40 系…"在 50 系上就是错的。
  //    其它开关仍可直接写字符串，这里兼容两种写法。
  if (!sw) return "";
  return typeof sw.desc === "function" ? (sw.desc() || "") : (sw.desc || "");
}

async function toggleSwitch(sw) {
  if (pendingSwitches.has(sw.k)) return;       // 上一个动作还没落地，忽略这次点击
  // ★ **锁住的开关点不动**（2026-10-06）：判据来自后端（`mfg_unlock_available`）；
  //   后端在 `set_component_addon` 里还会再拒一次 —— 这里只是别让用户白点。
  if (typeof sw.locked === "function" && sw.locked()) return;
  const next = !settings[sw.k];
  pendingSwitches.add(sw.k);
  settings[sw.k] = next;                       // 先动界面，避免点了没反应
  try {
    if (sw.apply) {
      const r = await sw.apply(next);
      // 后端回传 `config` = **你的选择已经落进配置**（它才是下次启动的依据）。
      const persisted = !!(r && r.config && typeof r.config === "object" && sw.k in r.config);
      if (r && r.ok === false && !persisted) {
        settings[sw.k] = !next;                // 后端根本没动手（例如非 50 系开 DLSS5）→ 回滚
        syncConfig(sw.k, !next);
        await showAlert("没能改这个开关", r.message || "未知原因");
        return;
      }
      if (r && r.ok === false && persisted) {
        // 做了但没做全（例如找不到注入源、游戏正在运行占用 dll）：**开关保持你点的样子**
        // （配置已记下），把遗留问题说清楚 —— 因为弹窗让开关自己弹回去才是真正的"关不掉"。
        await showAlert("开关已改，但有遗留问题", r.message
          || (r.warnings || []).join("\n") || "未知原因");
      }
      // 以后端落盘的结果为准（它才是下次启动的依据）
      const applied = persisted ? r.config[sw.k] : next;
      settings[sw.k] = applied;
      syncConfig(sw.k, applied);
    } else {
      await saveSetting(sw.k, next);
    }
    // ⚠️ **不再 `await refreshState()`**（2026-10-06 用户：「**这个按钮反应也太慢了吧，
    //    过了好几秒才会同步统一管理器和 mod 锁定快捷键**」）：`get_state` 是整份状态，
    //    等它回来界面才动，手感就是"点了没反应"。而开关值已经由后端回传的 `config`
    //    同步进 `store.state.config`（见上面 `syncConfig`）⇒ 刷新丢后台即可。
    refreshState().then(() => loadSettings()).catch(() => {});
  } catch (e) { /* call() 已经弹过窗 */ }
  finally { pendingSwitches.delete(sw.k); }
}

// 启动页日志 = **真实启动日志**（`runtime\logs\launch.log`，后端 `read_launch_log`）。
// 用户 2026-10-03：「现在日志展示的是 json，不是启动过程」—— 那次是我把 launch() 的
// 返回值 JSON.stringify 出来顶掉了日志。这里恢复成"跟日志"：
// 启动后立刻拉一次，然后 1.5 秒轮询一次，跟着看到「注入自检 / 拉起 XXMI / 进程监视」全过程。
let logTimer = null;
async function pullLaunchLog() {
  try {
    // 后端 `read_launch_log(tail)` 返回的是 `{ok, text}`（整段文本，不是数组）——
    // 一开始我按 `lines`/`log` 猜字段，结果拿不到内容。
    const r = await call("read_launch_log", 200);
    const text = (r && r.text) || "";
    if (!String(text).trim()) return;
    consoleLog.value = String(text)
      .split(/\r?\n/)
      .filter((ln) => ln.trim())
      .join("\n");
  } catch (e) { /* 读不到就保持原样 */ }
}
function startLogPolling() {
  if (logTimer) return;
  logTimer = setInterval(pullLaunchLog, 1500);
  // 一分钟足够覆盖"注入 → 拉起 XXMI → 进程监视"这段；之后停掉，不常驻
  setTimeout(() => { if (logTimer) { clearInterval(logTimer); logTimer = null; } }, 60000);
}
onUnmounted(() => {
  if (logTimer) clearInterval(logTimer);
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
});
// 每 3 秒看一次"游戏在不在跑"，只用来决定按钮布局（一次 IPC 查询，开销极小）
refreshGameLive();
liveTimer = setInterval(refreshGameLive, 3000);

// 往启动页日志框追加一行（带换行）。启动页日志有两个来源：
// `read_launch_log()` 轮询到的后端日志，以及前端自己这几句状态说明。
function appendLog(line) {
  const cur = consoleLog.value || "";
  consoleLog.value = (cur ? cur.replace(/\n+$/, "") + "\n" : "") + line;
}

// ── 启动前三段预警（2026-10-03 补回归）────────────────────────────────────────
// 返回 false = 用户选择不启动。

/** ① 异常状态预警：critical 必须**每次**弹、按钮要等够 N 秒才可点。 */
async function alertGate() {
  let gate = null;
  try {
    gate = await call("prelaunch_alerts");
  } catch (e) {
    return true;                 // 查不到就放行，不能因为检查本身挡住启动
  }
  if (!gate || !gate.blocking) return true;
  for (const a of (gate.alerts || [])) {
    // 用户要求"强制停留一定秒数"——秒数来自仓库里的 alerts.json（默认 10），
    // 作者改了 push 就生效、不用发版。
    const hold = Math.max(0, Number(a.hold_seconds || gate.hold_seconds || 10));
    const lines = [a.title || "异常状态", ""];
    if (a.body) lines.push(a.body, "");
    if (a.url) lines.push(`详情：${a.url}`, "");
    lines.push(
      hold > 0 ? `（请先读完，${hold} 秒后按钮才可点）` : "",
      "",
      "「还原配置」= 关掉所有注入开关 + 把游戏目录的第三方文件备份移走（可恢复）",
      "「保持配置」= 什么都不动，只是这次不启动",
      "「仍然启动」= 照常启动（配置有问题的话很可能起不来）",
    );
    // 三选一（用户 2026-09-30 定的顺序）：
    //   主按钮（橙色/最右）= **还原配置**（推荐动作，主选项）
    //   取消（最左）      = 保持配置但不启动
    //   额外按钮          = 仍然启动
    const choice = await showModalDialog({
      title: "检测到异常状态",
      message: lines.filter((x) => x !== "").join("\n"),
      okText: "还原配置（推荐）", cancelText: "保持配置，不启动",
      holdSeconds: hold,                                    // 强制停留（倒计时结束前按钮不可点）
      extraButtons: [{ text: "仍然启动", value: "launch" }],
    });
    const action = choice === "launch" ? "launch" : (choice === true ? "restore" : "hold");
    try {
      await call("alert_action", String(a.id || ""), action);
    } catch (e) { /* 后端会记日志 */ }
    if (action !== "launch") {
      appendLog(action === "restore" ? "已按你的选择还原配置，这次不启动。"
                                     : "已保持配置，这次不启动。");
      return false;
    }
    appendLog("你选择了「仍然启动」，继续。");
  }
  return true;
}

/** ② 启动前风险确认：资源冲突 / 崩溃记忆。 */
async function riskGate() {
  let risks = null;
  try {
    risks = await call("prelaunch_risks");
  } catch (e) {
    return true;
  }
  if (!risks || !risks.risky) return true;
  const conflicts = risks.conflicts || [];
  const crashed = risks.crashed || [];
  const lines = [];
  if (conflicts.length) {
    lines.push("**资源冲突**（这些 Mod 改的是同一批资源，同时开常常会让游戏崩）：");
    for (const c of conflicts.slice(0, 6)) {
      lines.push(`· ${c.label || c.group || "一组 Mod"}`);
    }
    lines.push("");
  }
  // ⚠️ 用户强调过：**不要把"以前崩过"说成"冲突"**，两者分开如实讲。
  if (crashed.length) {
    lines.push("**以前崩过**（这套组合在你这台机器上留下过崩溃记录）：");
    for (const c of crashed.slice(0, 6)) {
      lines.push(`· ${c.label || c.group || "一组 Mod"}${c.checked_at ? `（${c.checked_at}）` : ""}`);
    }
    lines.push("", "（以前崩过 ≠ 现在一定冲突；后来跑通过的话记录会被自动忽略。）");
  }
  const go = await showModalDialog({
    title: conflicts.length ? "发现 Mod 冲突风险" : "这套组合以前崩过",
    message: lines.join("\n"),
    // 用户定过：**推荐动作放最右的橙色主选项**（"先去清理"），"仍然启动"是次要项。
    okText: "先去清理", cancelText: "仍然启动",
    focusCancel: false,
  });
  if (go) {
    store.tab = "library";
    appendLog("已按提示先去清理冲突，这次不启动。");
    return false;
  }
  appendLog("你选择了「仍然启动」，继续。");
  return true;
}

/** ③ 文件守护：关键文件被反复删 ⇒ 建议加杀毒白名单。 */
async function fileWatchdogGate() {
  try {
    const st = store.state.file_watchdog;
    const info = (st && st.flagged) ? st : null;
    if (!info) return true;
    if (info.acknowledged) return true;          // 用户已经"不再提醒"
    const names = (info.files || []).slice(0, 6).map((f) => `· ${f.name || f}`).join("\n");
    const ok = await showModalDialog({
      title: "有文件被反复删除",
      message: [
        "这些关键文件被删掉过不止一次：",
        names || "（见日志）",
        "",
        "**多半是杀毒软件误删**。建议把下面这个目录加进杀毒软件的白名单：",
        String(info.watch_dir || store.state.data_root || ""),
        "",
        "选「知道了」以后不再提醒；选「继续提醒」则会保留这条提醒。",
      ].join("\n"),
      okText: "知道了，不再提醒", cancelText: "继续提醒我",
    });
    if (ok) {
      try { await call("file_watchdog_ack"); } catch (e) { /* 忽略 */ }
      await refreshState();
    }
    return true;                                  // 这条只是提醒，不拦启动
  } catch (e) {
    return true;
  }
}

// ── 杀毒软件（2026-10-04 用户要求：「杀毒有没有办法处理，或者检测加弹窗」）────────
// 与上面那条的分工：`fileWatchdogGate` 只能说"我们的文件反复不见了，多半是杀毒"（推断），
// 而这里读的是 **Windows Defender 自己的处置记录**（被隔离文件的原路径）—— 能点名。
//
// ⚠️ 页面一加载就发、**不 await**：一次检测要走 PowerShell 查 Defender（1~3 秒），
// 等用户点「一键启动」时结果通常已经回来了，所以下面那道闸门是同步读，不拖慢启动。
const antivirusInfo = ref(null);
call("antivirus_check").then((r) => { antivirusInfo.value = r || null; }).catch(() => { });
let antivirusPrompted = false;

/** ④ 杀毒软件：Defender 处置过与本程序相关的文件 ⇒ 告诉用户，并给一键还原。 */
async function antivirusGate() {
  const info = antivirusInfo.value;
  if (!info || antivirusPrompted) return true;
  const hits = info.detections || [];
  if (!hits.length) return true;
  antivirusPrompted = true;
  const names = [];
  for (const hit of hits.slice(0, 3)) {
    for (const f of (hit.files || []).slice(0, 3)) names.push(`· ${f}`);
  }
  const ok = await showModalDialog({
    title: "Windows Defender 处理过这些文件",
    message: [
      "Defender 最近隔离 / 删除了本程序或游戏要用的文件：",
      ...names,
      "",
      "缺了它们游戏可能起不来、或者装好的功能失效。点下面的按钮把它们从隔离区还原回去。",
      "若反复发生，可在设置里确认「自动加 Defender 白名单」是开着的（默认开）。",
    ].join("\n"),
    okText: "从隔离区还原", cancelText: "知道了",
  });
  if (!ok) return true;
  let done = 0;
  for (const hit of hits) {
    for (const f of (hit.files || []).slice(0, 3)) {
      try {
        const r = await call("antivirus_restore", f);
        if (r && r.ok) done += 1;
      } catch (e) { /* 单个失败不影响其它 */ }
    }
  }
  // ⚠️ **如实说结果**：`MpCmdRun -Restore` 会因威胁名/路径不匹配而失败（不同 Defender
  // 版本行为有差异）。所以成功才说成功，没成才指路日志 —— 不粉饰。
  showToast(done ? `已还原 ${done} 个文件` : "还原没成功，原始错误在日志里",
    done ? "success" : "danger");
  return true;
}

/** 三段预警按顺序跑；任一环节用户选择"不启动"就返回 false。 */
async function preflightGate() {
  if (!(await alertGate())) return false;
  if (!(await riskGate())) return false;
  await fileWatchdogGate();
  await antivirusGate();
  return true;
}

/**
 * 跳到「依赖」页并让它**自动开始下载**（用户 2026-10-04 要求：
 * 「**要是缺下载，应该跳转到依赖进行下载**」）。
 *
 * 复用现成机制（`store.autoStartDeps`）：依赖页 `onMounted` 看到标志就自己跑
 * 「一键下载依赖」—— 那条链路有线路切换、实时进度、可暂停、失败重试，
 * 比在启动页里静默下几十 MB 好得多（「修复」只负责本地能做的部分）。
 */
function goToDepsDownload(keys) {
  const list = Array.isArray(keys) ? keys.filter(Boolean) : [];
  appendLog(`有 ${list.length} 项需要联网下载：${list.join("、")} —— 已跳到「下载」页开始下载`);
  store.autoStartDepsNote = `完整性检查发现 ${list.length} 项缺失，开始联网下载补齐…`;
  store.autoStartDeps = true;
  store.tab = "downloads";     // 2026-10-07：组件下载也统一去「下载」页看进度
  showToast("已跳到「下载」页，正在开始下载…", "info");
}

// ⚠️ **B1：完整性检查要显示结果、并能一键修复**（2026-10-03 补回归）。
// 0.9.5（app.js:1957-1980）：`check_integrity` → 有缺失就弹「是否自动修复？」→
// `repair_integrity()` + 打开日志窗看进度。
// 换代后只剩 `run('check_integrity')`：**结果丢弃、`repair_integrity` 前端零调用** ——
// 标签写着「检查/修复完整性」，实际**只能检查、结果还看不见**。
async function checkIntegrity() {
  // ⚠️⚠️ **不能拿 `r.ok === false` 当"调用失败"**（2026-10-04 修）。
  // `integrity.check_integrity()` 的 `ok` 语义是"**没有 critical 缺失**"，而不是
  // "这个接口调通了" —— 于是真有缺失时这里直接 return，`run()` 只会弹一句
  // 「操作未完成 / 未知原因」（返回里没有 message），**"是否自动修复"这条闭环根本不可达**，
  // 用户点了「检查/修复完整性」永远得不到修复选项。
  let r = null;
  try {
    r = await call("check_integrity");
  } catch (e) {
    await showAlert("完整性检查失败", String((e && e.message) || e || "未知原因"));
    return null;
  }
  if (!r || typeof r !== "object") {
    await showAlert("完整性检查失败", "后端没有返回检查结果。");
    return null;
  }
  const checks = r.checks || [];
  const bad = checks.filter((c) => c.ok === false);
  const lines = checks.map((c) => `${c.ok ? "✓" : "✗"} ${c.message || c.key}${c.ok ? "" : `\n    ${c.path}`}`);
  if (!bad.length) {
    await showModalDialog({
      title: "完整性检查：全部正常", message: lines.join("\n") || "没有可检查的项。",
      okText: "知道了", showCancel: false,
    });
    return r;
  }
  // ⚠️ **区分"本地能修"和"要联网下载"**（2026-10-04 用户实测后要求）：
  // 他点「自动修复」后日志里是 `dlss5:d3d12.dll / dlss5:dlss5-feed.addon64 缺失且找不到素材来源`
  // —— 那两个文件上游都有（ReShade 官网 / DLSS5-Feeder），只是"修复"这条路**只找本地素材、
  // 不联网**（而且刻意不在启动页静默下载几十 MB）。他的要求是：
  // 「**要是缺下载，应该跳转到依赖进行下载**」⇒ 这里先告诉他哪些要下载，再把他送过去。
  const needDl = Array.isArray(r.needs_download) ? r.needs_download : [];
  const head = needDl.length
    ? `\n\n其中 **${needDl.length} 项需要联网下载**才能补齐：\n    ` + needDl.join("、")
    : "";
  const go = await showModalDialog({
    title: `完整性检查：${bad.length} 项缺失`,
    message: lines.join("\n") + head
      + "\n\n要不要现在自动修复？（**只做本地能做的**：补文件、写配置、重建 staging；需要下载的部分会引导你去「下载」页）",
    okText: needDl.length ? "去下载页下载" : "自动修复",
    cancelText: needDl.length ? "先本地修复" : "先不修",
  });
  // 主按钮 = 去「下载」页开始「一键下载依赖」（那条链路有进度、线路切换、可暂停）
  if (go && needDl.length) {
    goToDepsDownload(needDl);
    return r;
  }
  if (!go && needDl.length) {
    // 次要按钮：先只跑本地修复（补完再回来看还缺什么）
    // 落到下面的 repair 流程
  } else if (!go) {
    return r;
  }
  showProgressToast("integrity-repair", "正在修复完整性…（只做本地能做的部分）");
  try {
    const fixed = await call("repair_integrity");
    const after = (fixed && fixed.integrity && fixed.integrity.checks) || [];
    const stillBad = after.filter((c) => c.ok === false);
    const stillDl = (fixed && fixed.integrity && fixed.integrity.needs_download) || [];
    if (stillDl.length) {
      // 还有"要下载"的项 ⇒ 直接把用户送去「下载」页（这就是他说的"跳转到下载进行下载"）
      const again = await showModalDialog({
        title: `还有 ${stillDl.length} 项要联网下载`,
        message: "本地能做的都做完了；下面这些需要从网上取：\n    " + stillDl.join("、")
          + "\n\n要现在跳到「下载」页下载吗？（那边会显示线路与进度，可暂停）",
        okText: "去下载页下载", cancelText: "稍后自己弄",
      });
      if (again) goToDepsDownload(stillDl);
    } else {
      await showModalDialog({
        title: stillBad.length ? `修复完成，还有 ${stillBad.length} 项没修好` : "完整性已修复",
        message: stillBad.length
          ? stillBad.map((c) => `✗ ${c.message || c.key}\n    ${c.path}`).join("\n")
          : "所有缺失项都已补齐。",
        okText: "知道了", showCancel: false,
      });
    }
    await refreshState();
  } catch (e) {
    showToast(String((e && e.message) || "修复失败"), "danger");
  } finally {
    hideProgressToast("integrity-repair");
  }
  return r;
}

// ⚠️ **B7：清空日志**（0.9.5 的日志弹窗里有「清空」，`clear_launch_log` 前端零调用）。
async function clearLaunchLog() {
  const ok = await showModalDialog({
    title: "清空启动日志",
    message: "会清空 `runtime\\logs\\launch.log`。\n\n排查问题时日志很有用，建议**先导出一份诊断包**再清。",
    okText: "清空", cancelText: "保留日志", focusCancel: true,
  });
  if (!ok) return;
  const r = await run("clear_launch_log");
  if (r && r.ok !== false) {
    showToast("启动日志已清空", "success");
    await pullLaunchLog();
  }
}

async function oneClick() {
  // ─────────────────────────────────────────────────────────────────────────
  // ⚠️⚠️ **三段启动前预警**（2026-10-03 补回归）。0.9.5 里它们都在"拉起 XXMI 之前"，
  // 换代到 Vue 时整块丢了 —— 现前端 grep `prelaunch_alerts` / `alert_action` /
  // `prelaunch_risks` / `file_watchdog_ack` **全部 0 命中**，而后端这些接口一直健在
  //（`api.py:822/842/621/882/900`），连 `alerts.json` 的 `default_hold_seconds: 10`
  // 都还在仓库里等着被读。
  //
  // ① **异常状态预警**（A3）：用户 2026-09-30 原话 ——「在按一键启动的时候如果是异常状态
  //    要**每次都弹**弹窗展示情况，强制用户停留一定秒数（可在仓库配置，默认 10s），
  //    给出**还原配置（主选项）**、保持配置但不启动、仍然启动」。所以：不记已读、没有开关。
  // ② **启动前风险确认**（A2）：资源冲突 + 崩溃记忆，让用户决定"先去清理 / 仍然启动"。
  //    用户强调过文案不能把"以前崩过"说成"冲突"。
  // ③ **文件守护提醒**（A4）：关键文件被反复删 ⇒ 建议把目录加进杀毒白名单。
  // ─────────────────────────────────────────────────────────────────────────
  // ★★ **"正在启动"必须早于任何 await**（2026-10-06 修「点一次启动拉起 4 个 EFMI」）。
  //   以前 `running.value = true` 写在下面几个 await（`preflightGate` → 组件更新查询 →
  //   VC++ 查询）**之后**才设 ⇒ 那段时间按钮**仍然可点**，快速双击（日志实测两次相隔
  //   **68 毫秒**）就会并发跑进两趟完整流程、各调一次 `launch`，后端当时也不防重
  //   ⇒ 任务管理器里 4 个 XXMI Launcher，每个各挂一套 EFMI。
  //   后端现在有两道闸兜底（入口锁 + 拉起前查实例），这里补上"第一时间挡住按钮"。
  //   ⚠️ 提前返回的分支**必须复位**，否则按钮会永远灰着。
  if (running.value) return;
  running.value = true;
  if (!(await preflightGate())) { running.value = false; return; }

  // ⚠️ **用「随包版本表」检查组件更新**（2026-10-03 用户：「那个一键启动检查更新**还是要加**，
  //    但是是**随包资源里配一张版本表**，每次比对那个表，然后**随管理器更新而更新**，
  //    对旧版本**没有这个表，如果表不存在就跳过**」）。
  //
  // 与上一版的区别：上一版调 `check_component_updates`（**同步联网，实测 6.1 秒**），
  // 用户反馈"反应很慢"；这次读的是**随 exe 走的本地表**，微秒级，不会拖慢启动。
  // 旧版本 exe 没有那张表 ⇒ 后端返回空列表 ⇒ 这里自动跳过（不报错、不阻塞）。
  try {
    const upd = await call("pending_component_updates");
    const outdated = (upd && upd.outdated) || [];
    if (outdated.length) {
      const lines = outdated.map((o) => `· ${o.display || o.key}：${o.current} → ${o.latest}`).join("\n");
      const go = await showModalDialog({
        title: `${outdated.length} 个组件有新版本`,
        message:
          `这些组件有新版本可用：\n${lines}\n\n` +
          "去「下载」页点「一键更新全部组件」就能装上（那里有进度和速度）。\n\n" +
          "想先不管、直接启动也可以。",
        okText: "去下载页更新", cancelText: "仍然启动",
      });
      if (go) {
        store.autoStartDeps = true;
        store.tab = "downloads";   // 2026-10-07：组件更新也统一去「下载」页看进度
        return;
      }
    }
  } catch (e) { /* 查不到就照常启动，绝不因为它挡住用户 */ }

  // 缺 VC++ 运行库 ⇒ 先问一次（**建议安装**；跳过也照常启动，绝不挡流程）。
  // 依赖页那条走的是 `ensure_all` 的结果，这里走主动查询 —— 两条路共用同一个弹窗。
  try {
    const vc = await call("vc_runtime_status");
    if (vc && Array.isArray(vc.missing) && vc.missing.length) await promptVcRuntimeInstall();
  } catch (e) { /* 查不到就别挡启动 */ }

  running.value = true;
  try {
    await call("launch");
    renderApi.value = store.state.render_api || "";
    // ⚠️ **不要打印 launch() 的返回值**（2026-10-03 用户反馈：「现在日志展示的是 json，
    // 不是启动过程」）—— 我一度把那坨字典 `JSON.stringify` 出来，结果启动页日志窗
    // 全是 JSON，看不到真正的启动过程。
    // 启动页要的是**日志本身**：后端 `read_launch_log()` 读的就是 `runtime\logs\launch.log`
    //（与依赖页那个日志框同源）。先立刻拉一次，再开轮询持续跟。
    await pullLaunchLog();
    startLogPolling();
    // ⚠️⚠️ **一键启动的下半段**（2026-10-03 补回归）。
    // 0.9.5 是：`waitXxmiClosed()` 等 XXMI 退出 → `watchGameAfterXxmi()` 看终末地到底
    // 起没起来 → 没起来/刚起来就闪退 ⇒ 弹「再启动一次」。换代到 Vue 之后**整段丢了**
    // （现前端 grep `xxmi_running` / `game_running` / `first_run_state` **全 0 命中**），
    // 于是启动失败时用户只看到日志停了、没有任何提示 —— 而用户 2026-09-30 明确要求过
    // 「在 xxmi 退出后检测终末地状态，如果在拉起后 10s 内退出就弹弹窗」。
    // 这里用 `finally` 之外的独立流程跑，**不阻塞按钮的"正在启动…"状态**（可能要等十几分钟）。
    void watchLaunchOutcome();
  } catch (e) {
    consoleLog.value = (consoleLog.value || "") + "\n启动失败：" + (e && e.message ? e.message : String(e));
  } finally {
    running.value = false;
  }
}

// 等 XXMI Launcher 退出（最多 10 分钟）。
// 查询失败**当作它还在运行**继续等 —— 不因为一次查询失败就误判"已经退出了"。
async function waitXxmiClosed(timeoutMs = 10 * 60 * 1000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 2000));
    try {
      const state = await call("xxmi_running");
      if (!state || !state.running) return true;
    } catch (e) { /* 查询失败不拦路，继续等 */ }
  }
  return false;
}

// XXMI 退出之后，看终末地到底起没起来 —— 这才是"这一把成不成"的判据。
//   ① 等 Endfield.exe 出现（最多 30 秒，XXMI 退出到游戏进程出现之间有段空档）；
//   ② 出现后再盯 10 秒 —— 这 10 秒内就退出 = "启动失败"那种闪退；
//   ③ 没出现 / 10 秒内退出 ⇒ ok=false。
async function watchGameAfterXxmi(appearMs = 30000, aliveMs = 10000) {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const appearDeadline = Date.now() + appearMs;
  let sawGame = false;
  while (Date.now() < appearDeadline) {
    await sleep(1000);
    try {
      const g = await call("game_running");
      if (g && g.running) { sawGame = true; break; }
    } catch (e) { /* 查询失败继续等 */ }
  }
  if (!sawGame) return { ok: false, reason: "等了 30 秒没看到终末地进程 —— 游戏没有启动" };
  const aliveDeadline = Date.now() + aliveMs;
  while (Date.now() < aliveDeadline) {
    await sleep(1000);
    try {
      const g = await call("game_running");
      // 查询失败**当作还在跑**（不能因为一次查询失败就说人家崩了）
      if (g && !g.running) {
        return { ok: false, reason: "终末地启动后 10 秒内就退出了（启动失败）" };
      }
    } catch (e) { /* 当作还在跑 */ }
  }
  return { ok: true, reason: "" };
}

// 一键启动的收尾判定：等 XXMI 退出 → 看游戏起没起来 → 该提示就提示。
async function watchLaunchOutcome() {
  const xxmiClosed = await waitXxmiClosed();
  if (!xxmiClosed) {
    // 等了 10 分钟 XXMI 还开着：可能用户自己在里面点、或者卡住了。
    // **不弹窗打扰**（0.9.5 也是这样），只在日志里留一句。
    appendLog("等了 10 分钟 XXMI Launcher 还开着，就不再往下判定了（它可能还在正常工作）。");
    return;
  }
  // 「这一次算不算第一次启动」——**不能用 `first_run`**：它的判据是"三个内置组件里
  // 还有没装的"，只要有一个没装就为 true，与"这一把是不是第一次拉起 XXMI"无关。
  // 用户 2026-10-01 原话：「我说的第一次启动是在**拉起 xxmi 之后再谈**，
  // 选项应该是**再次启动**和**先不启动**」。
  let needSecondStart = false;
  try {
    const fr = await call("first_run_state");
    needSecondStart = !!(fr && (fr.first_run || fr.needs_second_start || fr.uninitialized));
  } catch (e) { /* 拿不到就不按"第一次"提示 */ }

  const game = await watchGameAfterXxmi();
  if (game.ok && !needSecondStart) return;      // 起来了、也不是第一次 → 静默成功

  const again = await showModalDialog({
    title: game.ok ? "第一次启动：请再点一次" : "终末地没有起来",
    message: game.ok
      ? [
          "看起来是第一次启动（内置组件刚装好 / 配置刚生成）。",
          "",
          "**终末地已经起来了**，但第一次常常会起不来或很快退出。",
          "如果它没进游戏，再点一次「一键启动」就好。",
        ].join("\n")
      : [
          game.reason,
          "",
          "**第一次启动有概率起不来**，再点一次通常就好了。",
          "如果连续几次都不行，去「依赖」页看运行日志和自检结果。",
        ].join("\n"),
    okText: "再次启动", cancelText: "先不启动",
  });
  if (again) {
    appendLog("按提示再来一次一键启动…");
    await oneClick();
  }
}
// ⚠️⚠️ **同 SettingsPage：`run()` 不能静默**（2026-10-03 统一修）。
// 原来 `catch { return null }` 把异常吞掉、也不看返回值 ⇒ 本页多个按钮"点了没反应"
//（「启动插件界面」「打开摆姿页」「生成控制器」「检查/修复完整性」…）。
async function run(method, ...args) {
  try {
    const result = await call(method, ...args);
    if (result && result.ok === false) {
      await showAlert("操作未完成", String(result.message || result.reason || "未知原因"));
    }
    return result;
  } catch (e) {
    await showAlert("操作失败", String((e && e.message) || e || "未知原因"));
    return null;
  }
}

// 日志框自动滚到底（不抢鼠标、没新内容不动）
const logBox = ref(null);
useLogAutoScroll(logBox, () => consoleLog.value);
</script>

<template>
  <div class="space-y-4">
    <!-- 终末地在跑 ⇒ 左右两个按钮（左「一键启动」/ 右「热重载」）；没跑 ⇒ 整宽单按钮。
         用户 2026-10-04 原话：「如果终末地在运行，现在一键启动那个位置左右切成两个按钮，
         左边一键启动，右边热重载……然后在终末地没运行的时候就像现在这样整个按钮横在那」。 -->
    <div class="flex gap-2">
      <button id="oneclick-launch-btn"
              :class="gameLive ? 'flex-1' : 'w-full'"
              class="py-4 rounded-lg text-white text-base font-semibold transition-colors"
              :disabled="running"
              :style="{ background: running ? 'var(--border-strong)' : 'var(--accent)' }"
              @click="oneClick">
        {{ running ? "正在启动…" : "一键启动" }}
      </button>
      <button v-if="gameLive"
              id="hot-reload-btn"
              class="flex-1 py-4 rounded-lg text-base font-semibold transition-colors"
              :disabled="hotReloading"
              :style="{ background: 'transparent',
                        color: hotReloading ? 'var(--text-muted)' : 'var(--text)',
                        border: '1px solid var(--border-strong)' }"
              @click="hotReload">
        {{ hotReloading ? "热重载中…" : "热重载" }}
      </button>
    </div>
    <!-- ★ **启动进度**（2026-10-07 用户要求："启动到扫除mod还是很慢，要是要时间就显示加载页面"）。
         后端在启动链的关键节点写 `launch_stage`（检查注入库 → 随包组件 → **重建 Mod 目录** →
         ReShade/面板 → 拉起 XXMI），前端本来就按 1~2 秒轮询 `get_state()`，直接显示即可。
         只在 `running` 时出现；读不到就什么也不显示（退回按钮文字，不占位）。 -->
    <p v-if="running && launchStageText"
       class="text-center text-xs mt-2"
       style="color: var(--text-muted)">
      {{ launchStageText }}
    </p>

    <Card title="注入开关">
      <div class="divide-y" style="border-color: var(--border)">
        <div v-for="sw in SWITCHES" :key="sw.k" class="switch-row"
             :style="sw.locked && sw.locked() ? 'opacity:.55;cursor:not-allowed' : ''"
             @click="toggleSwitch(sw)">
          <div class="min-w-0">
            <div class="font-medium">
              {{ sw.name }}
              <span v-if="sw.locked && sw.locked()" class="text-xs"
                    style="color: var(--text-muted)">（本机不适用）</span>
            </div>
            <div class="text-xs mt-0.5" style="color: var(--text-muted)">
              {{ sw.locked && sw.locked() ? sw.lockReason() : swText(sw) }}
            </div>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <span class="switch-state">{{ settings[sw.k] ? "已开启" : "已关闭" }}</span>
            <Switch :model-value="!!settings[sw.k]" :disabled="sw.locked && sw.locked()"
                    @update:model-value="() => toggleSwitch(sw)" />
          </div>
        </div>
      </div>
    </Card>

    <div class="flex flex-wrap gap-2">
      <Btn @click="run('launch_secondary_motion')">启动插件界面（乳摇管理器）</Btn>
      <Btn @click="run('open_poser_web_ui')">打开摆姿页（Poser）</Btn>
      <Btn @click="run('prepare_launch')">生成控制器</Btn>
      <Btn @click="checkIntegrity">检查/修复完整性</Btn>
      <Btn @click="run('audit_game_injections')">检查游戏目录注入</Btn>
      <span v-if="renderApi" class="text-xs self-center"
              :style="{ color: renderApiWarn ? 'var(--warn)' : 'var(--text-muted)' }">{{ renderApiText }}</span>
    </div>

    <div class="log-card">
      <div class="log-card-head">
        <span>运行日志</span>
        <!-- ⚠️ **清空日志**（2026-10-03 补回归）：0.9.5 的日志弹窗里有「清空」，
             换代后 `clear_launch_log` 前端零调用 —— 日志越滚越长却没法清。 -->
        <Btn size="sm" @click="clearLaunchLog">清空</Btn>
      </div>
      <div ref="logBox" class="log-box" style="max-height: 260px; border-radius: 0">{{ consoleLog }}</div>
    </div>
  </div>
</template>
