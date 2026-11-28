// SPDX-License-Identifier: AGPL-3.0-only
// 本机无障碍 / 自动化通道的**前端那一半**（2026-11-17 用户要求）。
//
// 用户原话：「我还想加个功能，需要一个无障碍功能，能有个 api 或者命令行，允许 ai 操作 ui，
// 比如切换页面，点击开关，滑动这种」。
//
// 分工：后端（endfieldmodcontroller/ui_automation.py）起一个只绑 127.0.0.1 的 HTTP 服务，
// 把请求排进队列；这里每 POLL_MS 问一次「有没有活要干」，然后在**真实 DOM 上**执行 ——
// `el.click()`、原生 value setter + input 事件、`scrollIntoView`。
//
// ⚠️ 为什么不让后端直接 `window.evaluate_js()`：EdgeChromium 后端要在 UI/STA 线程执行，
//    从 HTTP 工作线程调用不保险（可能抛错或把整个界面挂住）。走现有 js_api 桥最稳。
//
// ⚠️ 这里的任何异常都必须**吞掉**：无障碍通道坏掉绝不能把界面拖下水，也不能弹窗。

import { t } from "./i18n.js";

const POLL_MS = 300;
const MAX_ELEMENTS = 400;

const INTERACTIVE = [
  "button",
  "[role=switch]",
  "[role=tab]",
  "[role=button]",
  "a[href]",
  "input",
  "select",
  "textarea",
  "[data-mc-id]",
].join(",");

function escapeAttr(value) {
  return String(value == null ? "" : value).replace(/["\\]/g, "\\$&");
}

function isVisible(el) {
  try {
    if (!el || !el.getClientRects) return false;
    if (el.getClientRects().length === 0) return false;
    const style = window.getComputedStyle(el);
    if (!style) return true;
    return style.visibility !== "hidden" && style.display !== "none" && style.opacity !== "0";
  } catch (e) {
    return false;
  }
}

function cssPath(el) {
  const parts = [];
  let node = el;
  let depth = 0;
  while (node && node.nodeType === 1 && depth < 8) {
    const tag = node.tagName.toLowerCase();
    const parent = node.parentElement;
    if (!parent) {
      parts.unshift(tag);
      break;
    }
    let index = 1;
    for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling) {
      if (sib.tagName === node.tagName) index += 1;
    }
    parts.unshift(tag + ":nth-of-type(" + index + ")");
    if (node.id) {
      parts[0] = "#" + escapeAttr(node.id);
      break;
    }
    node = parent;
    depth += 1;
  }
  return parts.join(" > ");
}

function selectorOf(el) {
  const tagged = el.getAttribute ? el.getAttribute("data-mc-id") : "";
  if (tagged) return '[data-mc-id="' + escapeAttr(tagged) + '"]';
  if (el.id) return "#" + escapeAttr(el.id);
  return cssPath(el);
}

function textOf(el) {
  const raw = el.getAttribute ? (el.getAttribute("aria-label") || el.getAttribute("title") || "") : "";
  const inner = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
  const label = raw || inner;
  return label.length > 120 ? label.slice(0, 117) + "..." : label;
}

function roleOf(el) {
  const explicit = el.getAttribute ? el.getAttribute("role") : "";
  if (explicit) return explicit;
  const tag = el.tagName ? el.tagName.toLowerCase() : "";
  if (tag === "button") return "button";
  if (tag === "a") return "link";
  if (tag === "select") return "combobox";
  if (tag === "textarea") return "textbox";
  if (tag === "input") {
    const type = String(el.type || "text").toLowerCase();
    if (type === "checkbox") return "checkbox";
    if (type === "radio") return "radio";
    if (type === "range") return "slider";
    if (type === "file") return "file";
    return "textbox";
  }
  return "generic";
}

function readChecked(el) {
  if (!el) return false;
  const aria = el.getAttribute ? el.getAttribute("aria-checked") : null;
  if (aria != null) return String(aria) === "true";
  if ("checked" in el) return !!el.checked;
  return false;
}

function boundsOf(el) {
  try {
    const rect = el.getBoundingClientRect();
    return {
      x: Math.round(rect.left),
      y: Math.round(rect.top),
      w: Math.round(rect.width),
      h: Math.round(rect.height),
    };
  } catch (e) {
    return null;
  }
}

function describe(el) {
  const role = roleOf(el);
  const out = {
    id: selectorOf(el),
    role: role,
    label: textOf(el),
    tag: el.tagName ? el.tagName.toLowerCase() : "",
    disabled: !!(el.disabled || (el.getAttribute && el.getAttribute("aria-disabled") === "true")),
    bounds: boundsOf(el),
  };
  if (role === "switch" || role === "checkbox" || role === "radio") out.checked = readChecked(el);
  if (el.value != null && typeof el.value !== "object") out.value = String(el.value).slice(0, 200);
  if (el.type) out.input_type = String(el.type);
  return out;
}

function currentTab() {
  const holder = document.querySelector("[data-mc-current-tab]");
  return holder ? String(holder.getAttribute("data-mc-current-tab") || "") : "";
}

function snapshot() {
  const nodes = Array.prototype.slice.call(document.querySelectorAll(INTERACTIVE));
  const elements = [];
  for (const el of nodes) {
    if (elements.length >= MAX_ELEMENTS) break;
    if (!isVisible(el)) continue;
    elements.push(describe(el));
  }
  return {
    ok: true,
    tab: currentTab(),
    title: document.title,
    viewport: { width: window.innerWidth || 0, height: window.innerHeight || 0 },
    count: elements.length,
    elements: elements,
  };
}

function resolve(id) {
  const text = String(id == null ? "" : id).trim();
  if (!text) return null;
  if (text.indexOf("tab:") === 0) {
    const byTag = document.querySelector('[data-mc-id="' + escapeAttr(text) + '"]');
    if (byTag) return byTag;
  }
  try {
    return document.querySelector(text);
  } catch (e) {
    return null;
  }
}

function setValue(el, value) {
  const next = value == null ? "" : String(value);
  let proto = null;
  if (typeof HTMLTextAreaElement !== "undefined" && el instanceof HTMLTextAreaElement) {
    proto = HTMLTextAreaElement.prototype;
  } else if (typeof HTMLSelectElement !== "undefined" && el instanceof HTMLSelectElement) {
    proto = HTMLSelectElement.prototype;
  } else if (typeof HTMLInputElement !== "undefined" && el instanceof HTMLInputElement) {
    proto = HTMLInputElement.prototype;
  }
  const desc = proto ? Object.getOwnPropertyDescriptor(proto, "value") : null;
  if (desc && desc.set) desc.set.call(el, next);
  else el.value = next;
  // 用 window.Event：静态检查（tests/test_frontend_freevars.py）不许出现裸的全局构造调用。
  el.dispatchEvent(new window.Event("input", { bubbles: true }));
  el.dispatchEvent(new window.Event("change", { bubbles: true }));
}

function act(id, action, value) {
  const verb = String(action || "click").toLowerCase();
  // ⚠️ scroll-by **不需要元素**：整页滚动。必须在 resolve(id) 之前处理 ——
  //    否则传空 id 时会先撞上"找不到元素"（2026-11-18 端到端实测抓到的那条）。
  if (verb === "scroll-by") {
    const dy = Number(value);
    window.scrollBy(0, Number.isFinite(dy) ? dy : 300);
    return { ok: true, action: verb, scrollY: window.scrollY };
  }
  const el = resolve(id);
  if (!el) {
    return { ok: false, message: t("找不到元素：") + String(id) + t("（先用 GET /state 取快照）") };
  }
  try {
    if (verb === "click" || verb === "tap") {
      if (typeof el.focus === "function") el.focus();
      el.click();
      return { ok: true, action: verb, element: describe(el) };
    }
    if (verb === "set" || verb === "toggle") {
      const want = typeof value === "boolean" ? value : !readChecked(el);
      const now = readChecked(el);
      if (now !== want) el.click();
      return { ok: true, action: verb, changed: now !== want, element: describe(el) };
    }
    if (verb === "value" || verb === "type" || verb === "input") {
      if (typeof el.focus === "function") el.focus();
      setValue(el, value);
      return { ok: true, action: verb, element: describe(el) };
    }
    if (verb === "scroll") {
      el.scrollIntoView({ block: "center", inline: "nearest" });
      return { ok: true, action: verb, element: describe(el) };
    }
    if (verb === "focus") {
      if (typeof el.focus === "function") el.focus();
      return { ok: true, action: verb, element: describe(el) };
    }
      return { ok: false, message: t("不认识的动作：") + verb + t("（支持 click / set / value / type / scroll / scroll-by / focus）") };
  } catch (e) {
    return { ok: false, message: t("执行失败：") + String(e && e.message ? e.message : e) };
  }
}

function execute(command) {
  const kind = String(command && command.kind || "");
  const payload = (command && command.payload) || {};
  if (kind === "snapshot") return snapshot();
  if (kind === "act") return act(payload.id, payload.action, payload.value);
  return { ok: false, message: t("不认识的指令：") + kind };
}

let timer = null;
let running = false;

async function tick() {
  if (!running) return;
  try {
    const api = window.pywebview && window.pywebview.api;
    if (api && typeof api.ui_automation_poll === "function") {
      const response = await api.ui_automation_poll();
      const commands = (response && response.commands) || [];
      for (const command of commands) {
        let payload;
        try {
          payload = execute(command);
        } catch (e) {
          payload = { ok: false, message: String(e && e.message ? e.message : e) };
        }
        try {
          await api.ui_automation_result(command.id, JSON.stringify(payload));
        } catch (e) {
          /* 回传失败等于后端超时，它会自己报超时，这里不用弹窗 */
        }
      }
    }
  } catch (e) {
    /* 桥还没就绪 / 正在关闭：下一轮再试，绝不影响界面 */
  } finally {
    if (running) timer = setTimeout(tick, POLL_MS);
  }
}

export function startUiAutomation() {
  if (running) return;
  running = true;
  try {
    window.__mcUi = { version: 1, snapshot: snapshot, act: act, pollMs: POLL_MS };
  } catch (e) {
    /* 只影响调试便利性 */
  }
  timer = setTimeout(tick, POLL_MS);
}

export function stopUiAutomation() {
  running = false;
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
}
