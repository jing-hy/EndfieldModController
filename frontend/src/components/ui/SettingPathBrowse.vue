<!-- SPDX-License-Identifier: AGPL-3.0-only -->
<script setup>
// 路径输入 + 「浏览」按钮（评审：Windows 桌面工具让用户手打路径不合理）。
// 走后端 choose_path —— 它弹的是系统原生选择框。
import { settings, saveSetting } from "../../lib/settings.js";
import { call } from "../../lib/bridge.js";
import { t } from "../../lib/i18n.js";
// ⚠️ showAlert 以前**没导入**（2026-10-04 修）：下面那句提示会抛 ReferenceError，
// 又被本函数的 `catch (e) { /* call() 已经弹过窗 */ }` 吞掉 ⇒ 后端 choose_path
// 返回 ok=false（exe 里 tkinter 被排除时是常态）时，界面上就是"浏览点了没反应" ——
// 正是这段注释声称已经修好的那条。
import { showAlert } from "../../lib/dialog.js";
import Btn from "./Btn.vue";

const props = defineProps({
  k: { type: String, required: true },
  label: { type: String, default: "" },
  hint: { type: String, default: "" },
  placeholder: { type: String, default: "" },
  kind: { type: String, default: "dir" },   // dir | file
  // 2026-11-28（用户：「开了内置 xxmi 那些配置框应该全部变灰不让填」）：
  // 置灰时输入框与「浏览」都不可点 —— 此时路径由程序按内置布局自己决定，
  // 让用户填了也不会被用到，属于"看起来能改、其实无效"的那种坑。
  disabled: { type: Boolean, default: false },
});

async function browse() {
  try {
    const r = await call("choose_path", props.kind === "dir", props.label || "选择路径");
    if (r && r.ok && r.path) {
      await saveSetting(props.k, r.path);
      return;
    }
    // ⚠️⚠️ **失败必须让用户看见**（2026-10-03 用户报「浏览点了没反应」）。
    // 原来这里 `if (r && r.ok && r.path)` —— 失败时**什么都不做**，
    // 而 exe 里 tkinter 被排除、后端总返回 ok=false ⇒ 按钮就是"点了没反应"。
    const why = String((r && r.message) || "");
    if (why === "cancelled") return;          // 用户自己取消，不用弹
    await showAlert(
      "选不了路径",
      why || "系统没有返回可用的选择框。你可以直接把路径粘贴到输入框里。",
    );
  } catch (e) {
    /* call() 已经弹过窗 */
  }
}
</script>

<template>
  <div class="flex items-center gap-3 py-1.5" :class="{ 'opacity-50': disabled }">
    <span class="w-56 shrink-0 text-sm" :title="hint">{{ label }}</span>
    <input class="field flex-1" :placeholder="placeholder" :value="settings[props.k] ?? ''"
           :disabled="disabled" :title="disabled ? t('使用内置 XXMI/EFMI 时由程序自动管理') : hint"
           @change="saveSetting(props.k, $event.target.value)" />
    <Btn size="sm" :disabled="disabled" @click="browse">{{ t("浏览") }}</Btn>
  </div>
</template>
