<script setup>
// 全局弹窗宿主：渲染 uiState.dialog，语义与旧 app.js 的 showModalDialog 完全一致
// （正文用 textContent 等价方式渲染 → 这里直接用插值，**不解析 markdown**）。
import { ref, watch, nextTick, onUnmounted } from "vue";
import { uiState, resolveDialog } from "../lib/dialog.js";
import Btn from "./ui/Btn.vue";

// 破坏性动作默认把焦点放在**安全项**（取消）上 —— `focusCancel: true` 时。
// 用户定的交互准则：「破坏性动作写清后果、默认聚焦安全项」。
const cancelBtn = ref(null);
const okBtn = ref(null);

// ⚠️ **强制停留倒计时**（2026-10-03 加）。用户 2026-09-30 要求：异常状态预警必须
// "强制用户停留一定秒数（可在仓库配置，默认 10s）" —— 倒计时结束前所有按钮不可点。
// 这是"必须让人看见"类提示的硬要求，不是装饰。
const holdLeft = ref(0);
let holdTimer = null;

function stopHold() {
  if (holdTimer) { clearInterval(holdTimer); holdTimer = null; }
  holdLeft.value = 0;
}

watch(() => uiState.dialog, async (dialog) => {
  stopHold();
  if (!dialog) return;
  await nextTick();
  const target = dialog.focusCancel ? cancelBtn.value : okBtn.value;
  if (target && target.focus) target.focus();
  const hold = Number(dialog.holdSeconds || 0);
  if (hold > 0) {
    holdLeft.value = hold;
    holdTimer = setInterval(() => {
      holdLeft.value -= 1;
      if (holdLeft.value <= 0) stopHold();
    }, 1000);
  }
}, { immediate: true });

onUnmounted(stopHold);
</script>
<template>
  <div v-if="uiState.dialog" class="fixed inset-0 z-50 flex items-center justify-center"
       style="background: rgba(0,0,0,.45)">
    <!-- ⚠️ `min-w-0` + `overflow-hidden` 是关键：卡片是 flex 子项，而 flex 子项默认
         `min-width: auto` —— 里面的超长路径会把整张卡片**顶宽**，光给 <pre> 加折行还不够。 -->
    <div class="card w-[min(560px,92vw)] min-w-0 overflow-hidden shadow-lg" style="background: var(--surface)">
      <div class="card-head">{{ uiState.dialog.title }}</div>
      <div class="card-body min-w-0">
        <!-- ⚠️ 长路径必须在**斜杠处自然折行**（用户 2026-10-03：「不是限高的问题，应该是限宽的问题，
             好像一个路径必须要一行显示完，实际可以在 / 处换行」）。
             `break-words`（overflow-wrap: break-word）**不够** —— 它只在"整个单词放不下"时才断，
             而 Windows 路径没有空格、会被当成**一个超长单词**，于是一行撑出弹窗外。
             `overflow-wrap: anywhere` 允许在任意字符处断行（含 `/`），再配 `max-width: 100%`
             把宽度约束在弹窗内；限高 + 滚动是额外保险（超长堆栈仍然要能看全）。 -->
        <pre class="whitespace-pre-wrap m-0 text-sm leading-6"
             style="max-width: 100%; overflow-wrap: anywhere; word-break: break-word;
                    max-height: 46vh; overflow-y: auto">{{ uiState.dialog.message }}</pre>
        <a v-if="uiState.dialog.link && uiState.dialog.link.url" :href="uiState.dialog.link.url"
           class="text-accent text-xs mt-2 inline-block" @click.prevent="$emit('open-link', uiState.dialog.link.url)">
          {{ uiState.dialog.link.text || uiState.dialog.link.url }}
        </a>
      </div>
      <div class="px-4 py-3 flex justify-end gap-2 border-t items-center" style="border-color: var(--border)">
        <!-- 强制停留：倒计时没走完时所有按钮都不可点（用户要求"强制用户停留一定秒数"） -->
        <span v-if="holdLeft > 0" class="text-xs mr-auto" style="color: var(--text-muted)">
          请先读完（{{ holdLeft }} 秒后可操作）
        </span>
        <Btn v-if="uiState.dialog.showCancel" ref="cancelBtn" variant="secondary"
             :disabled="holdLeft > 0" @click="resolveDialog(false)">
          {{ uiState.dialog.cancelText }}
        </Btn>
        <Btn v-for="b in uiState.dialog.extraButtons" :key="b.text" variant="secondary"
             :disabled="holdLeft > 0"
             @click="resolveDialog(b.value === undefined ? true : b.value)">{{ b.text }}</Btn>
        <Btn ref="okBtn" variant="primary" :disabled="holdLeft > 0"
             @click="resolveDialog(true)">{{ uiState.dialog.okText }}</Btn>
      </div>
    </div>
  </div>
</template>
