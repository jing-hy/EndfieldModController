<!-- SPDX-License-Identifier: AGPL-3.0-only -->
<script setup>
import { settings, saveSetting } from "../../lib/settings.js";
import { t } from "../../lib/i18n.js";
const props = defineProps({
  k: { type: String, required: true },
  label: { type: String, default: "" },
  options: { type: Array, default: () => [] },   // [{ value, label }]
});
</script>
<template>
  <div class="flex items-center gap-3 py-1.5">
    <span class="w-56 shrink-0 text-sm">{{ label }}</span>
    <select class="field flex-1" :value="settings[props.k] ?? ''"
            @change="saveSetting(props.k, $event.target.value)">
      <!-- 空值也要有一条明确选项（评审：下拉显示空白，用户不知道是"没设置"还是坏了） -->
      <option v-if="!options.some((o) => o.value === '')" value="">{{ t("自动（按当前网络决定）") }}</option>
      <option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option>
    </select>
  </div>
</template>
