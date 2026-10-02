<script setup>
import { settings, saveSetting } from "../../lib/settings.js";
import Switch from "./Switch.vue";
const props = defineProps({
  k: { type: String, required: true },
  label: { type: String, default: "" },
  hint: { type: String, default: "" },
});
</script>
<template>
  <div class="flex items-center justify-between gap-4 py-2">
    <span class="text-sm min-w-0" :title="hint">{{ label }}</span>
    <Switch :model-value="!!settings[props.k]" @update:model-value="(v) => saveSetting(props.k, v)" />
  </div>
</template>
