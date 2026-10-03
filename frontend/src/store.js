// 全局状态：与后端 get_state() 的返回同构，页面组件只读它 + 调后端后刷新。
import { reactive } from "vue";
import { call } from "./lib/bridge.js";

export const PAGE_IDS = ["library", "assist", "dependencies", "launch", "settings", "about"];

export const store = reactive({
  ready: false,
  state: {},            // get_state() 原样存
  // 初始页支持深链（`index.html#settings`）—— 截图 / 排查时能直接落到某一页
  tab: (() => {
    try {
      const hash = String(location.hash || "").replace(/^#/, "");
      return PAGE_IDS.includes(hash) ? hash : "library";
    } catch (e) { return "library"; }
  })(),
  // 若干页面共用的派生信息
  mods: [],
  config: {},
  // **封面缓存放在 store 里**（不是页面组件里）—— 后端每张封面都要 PIL 打开+缩放+JPEG 编码，
  // 放在组件里的话"切走再切回来 = 组件销毁 = 缓存清空 = 全部重新请求"，
  // 用户看到的就是"图片加载很慢"（2026-10-03 反馈）。放这里整个会话只取一次。
  covers: {},
  demoCovers: null,
  // 设置页点「依赖清空并重新下载」→ 清完跳到依赖页，由依赖页读这个标志自动开跑
  autoStartDeps: false,
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
  store.mods = (data && data.mods) || [];
  store.config = (data && data.config) || {};
  store.ready = true;
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
