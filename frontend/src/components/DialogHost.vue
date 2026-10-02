<script setup>
// 全局弹窗宿主：渲染 uiState.dialog，语义与旧 app.js 的 showModalDialog 完全一致
// （正文用 textContent 等价方式渲染 → 这里直接用插值，**不解析 markdown**）。
import { uiState, resolveDialog } from "../lib/dialog.js";
import Btn from "./ui/Btn.vue";
</script>
<template>
  <div v-if="uiState.dialog" class="fixed inset-0 z-50 flex items-center justify-center"
       style="background: rgba(0,0,0,.45)">
    <div class="card w-[min(560px,92vw)] shadow-lg" style="background: var(--surface)">
      <div class="card-head">{{ uiState.dialog.title }}</div>
      <div class="card-body">
        <pre class="whitespace-pre-wrap break-words m-0 text-sm leading-6">{{ uiState.dialog.message }}</pre>
        <a v-if="uiState.dialog.link && uiState.dialog.link.url" :href="uiState.dialog.link.url"
           class="text-accent text-xs mt-2 inline-block" @click.prevent="$emit('open-link', uiState.dialog.link.url)">
          {{ uiState.dialog.link.text || uiState.dialog.link.url }}
        </a>
      </div>
      <div class="px-4 py-3 flex justify-end gap-2 border-t" style="border-color: var(--border)">
        <Btn v-if="uiState.dialog.showCancel" variant="secondary" @click="resolveDialog(false)">
          {{ uiState.dialog.cancelText }}
        </Btn>
        <Btn v-for="b in uiState.dialog.extraButtons" :key="b.text" variant="secondary"
             @click="resolveDialog(b.value === undefined ? true : b.value)">{{ b.text }}</Btn>
        <Btn variant="primary" @click="resolveDialog(true)">{{ uiState.dialog.okText }}</Btn>
      </div>
    </div>
  </div>
</template>
