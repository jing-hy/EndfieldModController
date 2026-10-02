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
});

export async function refreshState() {
  const data = await call("get_state");
  store.state = data || {};
  store.mods = (data && data.mods) || [];
  store.config = (data && data.config) || {};
  store.ready = true;
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
