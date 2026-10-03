<script setup>
// `ref` 到本组件拿到的是**组件实例**（不是 DOM），所以显式转发 `focus` ——
// DialogHost 需要它把焦点放到安全项上（破坏性动作默认聚焦"取消"）。
import { ref } from "vue";

defineProps({ variant: { type: String, default: "secondary" }, size: { type: String, default: "md" }, disabled: Boolean });

const el = ref(null);
function focus() { if (el.value) el.value.focus(); }
defineExpose({ focus });
</script>
<template>
  <button ref="el" :class="['btn', `btn-${variant}`, size !== 'md' ? `btn-${size}` : '']" :disabled="disabled">
    <slot />
  </button>
</template>
