// SPDX-License-Identifier: AGPL-3.0-only
// 轻量 i18n（2026-11-28 用户要求英文界面 + 设置页语言切换，默认中文）。
// key = 中文原文：zh 直接返回原文，en 查字典（翻不到的仍显示中文）。
// 语言值写进 config.json 的 `language`（zh / en），localStorage 只做首帧回填。
import { reactive } from "vue";
import { call } from "./bridge.js";

function initialLang() {
  try {
    return localStorage.getItem("mc-lang") === "en" ? "en" : "zh";
  } catch (e) { return "zh"; }
}

export const i18n = reactive({ lang: initialLang() });

// 英文词典按文件拆开（lib/i18n/en/*.js，每个导出一个 { "中文": "English" }），
// 构建时由 Vite 的 glob 导入合并 —— 多人/子任务并行翻译各写各的片段，避免改同一个文件。
const EN_MODULES = import.meta.glob("./i18n/en/*.js", { eager: true });
const EN = Object.assign({}, ...Object.values(EN_MODULES).map((m) => (m && m.default) || {}));

export function t(key) {
  const text = String(key == null ? "" : key);
  if (!text) return "";
  if (i18n.lang !== "en") return text;
  return EN[text] || text;
}

export function applyLang(value) {
  const v = String(value || "").toLowerCase() === "en" ? "en" : "zh";
  i18n.lang = v;
  try { localStorage.setItem("mc-lang", v); } catch (e) { /* 隐私模式 */ }
  try { document.documentElement.setAttribute("lang", v === "en" ? "en" : "zh-CN"); } catch (e) { /* 忽略 */ }
}

export async function setLang(value) {
  applyLang(value);
  try {
    await call("save_config", { language: i18n.lang });
  } catch (e) { /* 写盘失败不影响本次生效 */ }
  return i18n.lang;
}

export function currentLang() {
  return i18n.lang;
}