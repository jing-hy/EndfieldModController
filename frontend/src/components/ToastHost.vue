<script setup>
import { uiState } from "../lib/dialog.js";
</script>
<template>
  <div class="fixed top-4 left-1/2 -translate-x-1/2 z-[60] flex flex-col gap-2 items-center pointer-events-none">
    <div v-for="t in uiState.toasts" :key="t.id"
         class="px-4 py-2 rounded-full text-sm shadow-md"
         style="background: var(--surface); border: 1px solid var(--border); color: var(--text)">
      {{ t.text }}
    </div>
  </div>
</template>
