// SPDX-License-Identifier: GPL-3.0-or-later
import { createApp } from "vue";
import App from "./App.vue";
import "./styles/tokens.css";
// 无障碍 / 自动化通道的前端那一半（2026-11-17 用户要求：允许 AI 操作界面）。
// 它每 300ms 问一次后端「有没有界面动作要执行」，拿到就在真实 DOM 上点/填/滚。
// 挂载之后再启动：那时 #app 里已经有可交互元素了。
import { startUiAutomation } from "./lib/uiAutomation.js";

createApp(App).mount("#app");
startUiAutomation();
