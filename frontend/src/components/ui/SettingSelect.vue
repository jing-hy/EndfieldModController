<script setup>
import { settings, saveSetting } from "../../lib/settings.js";
const props = defineProps({
  k: { type: String, required: true },
  label: { type: String, default: "" },
  options: { type: Array, default: () => [] },   // [{ value, label }]
});
</script>
<template>
  <div class="flex items-center gap-3 py-1.5">
    <span class="w-56 shrink-0 text-sm">{{ label }}</span>
    <select class="field flex-1" :value="settings[props.k]" @change="saveSetting(props.k, $event.target.value)">
      <option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option>
    </select>
  </div>
</template>
