<script setup>
// 设置项开关：**整行可点**（评审：只有右侧 40x22 能点到，容易点空）+ 显示状态文字。
import { settings, saveSetting } from "../../lib/settings.js";
import Switch from "./Switch.vue";
const props = defineProps({
  k: { type: String, required: true },
  label: { type: String, default: "" },
  hint: { type: String, default: "" },
});
</script>
<template>
  <div class="switch-row" :title="hint" @click="saveSetting(props.k, !settings[props.k])">
    <span class="text-sm min-w-0">{{ label }}</span>
    <span class="flex items-center gap-2 shrink-0">
      <span class="switch-state">{{ settings[props.k] ? "已开启" : "已关闭" }}</span>
      <Switch :model-value="!!settings[props.k]" @update:model-value="(v) => saveSetting(props.k, v)" />
    </span>
  </div>
</template>
