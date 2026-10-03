<script setup>
// 顶部的轻提示。评审指出"状态只靠左侧色条，色盲用户分不出成功/失败"——
// 所以这里**图标 + 颜色**双重表达，并按长度限制宽度（原来短句也被拉得很宽）。
import { uiState } from "../lib/dialog.js";
import { CheckCircle2, AlertTriangle, XCircle, Info } from "lucide-vue-next";

const ICONS = { success: CheckCircle2, warn: AlertTriangle, danger: XCircle, info: Info };
const COLORS = {
  success: "var(--success)", warn: "var(--warn)", danger: "var(--danger)", info: "var(--accent)",
};
</script>

<template>
  <div class="fixed top-4 left-1/2 -translate-x-1/2 z-[60] flex flex-col gap-2 items-center pointer-events-none"
       style="width: min(calc(100% - 32px), 420px)">
    <div v-for="t in uiState.toasts" :key="t.id"
         class="w-full px-3.5 py-2.5 rounded-lg text-sm shadow-md flex items-start gap-2"
         style="background: var(--surface); border: 1px solid var(--border); color: var(--text)">
      <component :is="ICONS[t.tone] || Info" :size="15" class="shrink-0"
                 :style="{ color: COLORS[t.tone] || COLORS.info, marginTop: '2px' }" />
      <span class="min-w-0">{{ t.text }}</span>
    </div>
  </div>
</template>
