<script setup>
import { settings, saveSetting } from "../../lib/settings.js";
const props = defineProps({
  k: { type: String, required: true },
  label: { type: String, default: "" },
  hint: { type: String, default: "" },
  placeholder: { type: String, default: "" },
  readonly: Boolean,
});
</script>
<template>
  <div class="flex items-center gap-3 py-1.5">
    <span class="w-56 shrink-0 text-sm" :title="hint">{{ label }}</span>
    <input class="field flex-1" :readonly="readonly" :placeholder="placeholder"
           :value="settings[props.k] ?? ''"
           @change="saveSetting(props.k, $event.target.value)" />
  </div>
</template>
