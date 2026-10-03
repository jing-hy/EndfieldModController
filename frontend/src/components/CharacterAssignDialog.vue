<script setup>
// 「更换归属」弹窗 —— 真正带下拉的角色选择器。
//
// ⚠️ 原来这里用的是 `showModalDialog`，而它**只返回 true/false、不含输入控件**，
// 所以文案写着"输入角色名（留空 = 保持未分类）"却**根本没有输入框**，
// 代码里 `pick === true ? "" : String(pick)` 于是**永远把归属设成空**
// （用户 2026-10-03：「更改角色归属就只有一个弹窗，没有选项框，而且说了留空 = 保持未分类，
//  设定又说不能留空」—— 前后矛盾正是这么来的）。
//
// 现在：下拉列出全部已知角色 + 一个明确的「（未分类）」选项，
// 两者语义写清楚：不选角色 = 保持未分类，这是**允许**的。
import { ref, computed } from "vue";
import { call } from "../lib/bridge.js";
import { showToast, showAlert } from "../lib/dialog.js";
import Btn from "./ui/Btn.vue";

const target = ref(null);      // 正在改的 mod
const chars = ref([]);
const picked = ref("");
const busy = ref(false);

const open = computed(() => !!target.value);

async function openFor(mod) {
  target.value = mod;
  picked.value = String(mod.group || "");
  try {
    const r = await call("known_characters");
    chars.value = (r && (r.characters || r.items)) || [];
  } catch (e) { chars.value = []; }
}

async function save() {
  if (!target.value) return;
  busy.value = true;
  try {
    const r = await call("set_mod_character", target.value.id, String(picked.value || ""));
    if (r && r.ok === false) {
      await showAlert("设定失败", r.message || "未知原因");
    } else {
      showToast(picked.value ? `已归到「${picked.value}」` : "已设为未分类（不参与同角色互斥）", "success");
      target.value = null;
    }
  } catch (e) { /* call 已弹窗 */ } finally {
    busy.value = false;
  }
}

defineExpose({ openFor });
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center" style="background: rgba(0,0,0,.45)">
    <div class="card w-[min(460px,94vw)] shadow-lg" style="background: var(--surface)">
      <div class="card-head">「{{ target.name }}」归到哪个角色？</div>
      <div class="card-body">
        <select v-model="picked" class="field w-full">
          <option value="">（未分类 —— 不参与同角色互斥）</option>
          <option v-for="name in chars" :key="name" :value="name">{{ name }}</option>
        </select>
        <p class="text-xs mt-2" style="color: var(--text-muted)">
          选一个角色后，同一个角色的其它 Mod 会自动取消勾选（防止两个同角色 Mod 同时生效把游戏搞崩）。
          <b>不选角色（未分类）也可以</b> —— 那样它就不参与互斥，适合壁纸、加载页这类不属于任何角色的 Mod。
        </p>
      </div>
      <div class="px-4 py-3 flex justify-end gap-2 border-t" style="border-color: var(--border)">
        <Btn @click="target = null">取消</Btn>
        <Btn variant="primary" :disabled="busy" @click="save">设定归属</Btn>
      </div>
    </div>
  </div>
</template>
