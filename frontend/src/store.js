// 全局状态：与后端 get_state() 的返回同构，页面组件只读它 + 调后端后刷新。
import { reactive } from "vue";
import { call } from "./lib/bridge.js";

export const PAGE_IDS = ["library", "assist", "dependencies", "launch", "settings", "about"];

export const store = reactive({
  // ⚠️ 依赖页的日志框内容放**全局**（2026-10-03 用户实测：「下载的时候切到其他页面，
  // 再切回依赖，就会清空日志」）。原先是 `DepsPage.vue` 里的局部 `ref` ——
  // 组件一销毁内容就没了；而后端的任务状态其实还在跑，回来却看到空白。
  // 放 store 里，组件重建时直接接着显示。
  depLogLines: [],
  depSpeedBps: 0,
  depModDlActive: false,
  ready: false,
  state: {},            // get_state() 原样存
  // **界面主题的唯一真源**（2026-10-04）：侧栏菜单与设置页下拉都读写它，
  // 别再各自维护一份（见文件末尾 setTheme 的说明）。初值取 localStorage，
  // 与 index.html `<head>` 里的内联脚本保持一致。
  theme: currentTheme(),
  // 初始页支持深链（`index.html#settings`）—— 截图 / 排查时能直接落到某一页
  tab: (() => {
    try {
      const hash = String(location.hash || "").replace(/^#/, "");
      return PAGE_IDS.includes(hash) ? hash : "library";
    } catch (e) { return "library"; }
  })(),
  // 若干页面共用的派生信息
  // ⚠️ 2026-10-04 删掉 `mods`（**只写不读**：全项目 grep 只有两处赋值，所有页面读的都是
  // `store.state.mods`）—— 两个"真源"并存最容易让人改错那一份。
  config: {},
  // **封面缓存放在 store 里**（不是页面组件里）—— 后端每张封面都要 PIL 打开+缩放+JPEG 编码，
  // 放在组件里的话"切走再切回来 = 组件销毁 = 缓存清空 = 全部重新请求"，
  // 用户看到的就是"图片加载很慢"（2026-10-03 反馈）。放这里整个会话只取一次。
  covers: {},
  demoCovers: null,
  // ⚠️ `demoPending` 原先**没有在这里声明**，只在 App.vue 里动态赋值（`store.demoPending = …`），
  // 而 `CharacterPickerDialog` 会读它 —— Vue 3 的 reactive 支持新增属性，但"先读后写"时
  // 拿到的是 undefined（demo 模式下表现为"角色确认窗是空的"）。显式声明成 null（2026-10-04）。
  demoPending: null,
  // 设置页点「依赖清空并重新下载」→ 清完跳到依赖页，由依赖页读这个标志自动开跑
  autoStartDeps: false,
  // Mod 下载开始后跳到依赖页（那儿的日志框显示下载过程）
  autoStartModDownload: false,
});

// 「每次状态刷新之后要做的事」注册表。
// 背景（2026-09-30 踩过、2026-10-03 仍然存在）：公告由后端**后台线程**拉取，而它要先等
// 前端首屏就绪（最多 15 秒）再请求 —— 前端只在启动那一刻读一次 state.announcements，
// 那时数据还没到，之后 refreshState() 刷了很多次却**没有人再读**，于是公告永远不弹。
// 定式：把消费做成**幂等函数**并挂在数据刷新点上，而不是指望某个固定时刻数据已就位。
const afterRefresh = [];

export function onStateRefreshed(hook) {
  if (typeof hook === "function" && !afterRefresh.includes(hook)) afterRefresh.push(hook);
}

// 给 get_state 加超时：没有桥、或后端卡住时 `call()` 可能**既不 resolve 也不 reject**，
// 直接把 await 它的调用方（例如公告消费）永久挂住。超时后按"这次没拿到"处理。
function withTimeout(promise, ms, fallback) {
  return Promise.race([
    promise,
    new Promise((resolve) => setTimeout(() => resolve(fallback), ms)),
  ]);
}

export async function refreshState() {
  const data = await withTimeout(call("get_state"), 8000, null);
  if (!data) return null;      // 没拿到就保持原样，别把 store 清空
  store.state = data || {};
  store.config = (data && data.config) || {};
  store.ready = true;
  // 主题：**以 config 为准**回填界面真源（两个入口最终收敛到同一份持久设置；
  // 只在真的不一样时才动，避免每次刷新都重设 data-theme 引发闪烁）。
  const cfgTheme = String((data && data.config && data.config.theme) || "");
  if (cfgTheme && THEMES.includes(cfgTheme) && cfgTheme !== store.theme) {
    applyTheme(cfgTheme);
    store.theme = cfgTheme;
  }
  // 刷新后的消费点（公告之类的"后台线程稍后才产出"的数据要靠这里补上 —— 见 App.vue）
  for (const hook of afterRefresh) {
    try { hook(store.state); } catch (e) { /* 单个消费方出错不影响刷新本身 */ }
  }
  return data;
}

// 主题：沿用旧版的 6 套与 localStorage 键名（不能改，否则用户的设置会丢）
export const THEMES = ["light", "dark", "amber", "cyan", "violet", "emerald"];
export function applyTheme(theme) {
  const value = THEMES.includes(theme) ? theme : "light";
  document.documentElement.setAttribute("data-theme", value);
  try { localStorage.setItem("mc-theme", value); } catch (e) { /* 隐私模式忽略 */ }
}
export function currentTheme() {
  try { return localStorage.getItem("mc-theme") || "light"; } catch (e) { return "light"; }
}

/**
 * 切换主题 —— **唯一入口**（2026-10-04 用户拍板"统一两套真相"）。
 *
 * 原先有两个各自为政的入口：侧栏菜单（`App.vue.pickTheme`）**只写 localStorage**，
 * 设置页下拉（`SettingsPage.changeTheme`）写 config.json + localStorage —— 于是
 * 侧栏切完设置页下拉不动、设置页切完侧栏标签不变，用户看不出"到底设上没有"。
 *
 * 现在：`store.theme` 是**界面上的单一真源**，三件事一起做 ——
 *   ① `applyTheme()` 立刻生效（data-theme + localStorage，首屏内联脚本读的就是它）；
 *   ② `store.theme` 更新（侧栏标签与设置页下拉都读它）；
 *   ③ 写进 config.json（持久化；失败**静默**，主题不该因为写盘失败而不生效）。
 */
export async function setTheme(name) {
  const value = THEMES.includes(name) ? name : "light";
  applyTheme(value);
  store.theme = value;
  try {
    if (store.state && store.state.config) store.state.config.theme = value;
  } catch (e) { /* 忽略 */ }
  try {
    await call("save_config", { theme: value });
  } catch (e) { /* 写盘失败不影响本次生效 */ }
  return value;
}
