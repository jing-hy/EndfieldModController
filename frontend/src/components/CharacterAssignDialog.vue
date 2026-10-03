<script setup>
// 「归类」对话框 —— **两个下拉**（用户 2026-10-03 明确的设计）：
//   「那个下拉可以拆成两个，上面一个选择是服装还是辅助，下面那个选择细分」
//
// 为什么必须拆开：原先只有一个"角色"下拉，而辅助 Mod 的**分组名**
//（加载页与壁纸 / 界面功能类 / 工具画质类 / 其它辅助）也被列了进去，
// 一选就被当成角色写进 `mod.meta.json`，于是角色表里凭空多出一个
// 叫「加载页与壁纸」的"角色"（用户实测报的 bug）。
// 类型（服装/辅助）与细分（角色/分组）本来就是**两个维度**，分两个下拉就不再有歧义。
import { ref, computed } from "vue";
import { call } from "../lib/bridge.js";
import { showToast, showAlert } from "../lib/dialog.js";
import Btn from "./ui/Btn.vue";

const target = ref(null);      // 正在改的 mod
const chars = ref([]);         // 角色列表（服装用）
const kind = ref("character"); // "character"（服装）| "assist"（辅助）
const picked = ref("");        // 细分：角色名 或 分组名
const busy = ref(false);

const open = computed(() => !!target.value);

// 辅助 Mod 的分组 —— 与后端 `core.WALLPAPER_GROUP` / `ASSIST_GROUP_*` 对齐
const ASSIST_GROUPS = ["加载页与壁纸", "界面功能类", "工具画质类", "其它辅助"];

const isAssist = computed(() => kind.value === "assist");

async function openFor(mod) {
  target.value = mod;
  // 初始类型：库里已经判成辅助的（或 group 命中辅助分组名的）就按辅助打开
  const g = String(mod.group || "");
  kind.value = (mod.kind === "assist" || ASSIST_GROUPS.includes(g)) ? "assist" : "character";
  picked.value = kind.value === "assist" ? (ASSIST_GROUPS.includes(g) ? g : "其它辅助") : g;
  try {
    const r = await call("known_characters");
    // ⚠️ 后端 `known_characters()` 返回的是**纯数组 list[str]**（不是 {characters:[...]}），
        // 原先按对象读 ⇒ 永远拿到空数组 ⇒「更改所属角色」的下拉里一个角色都没有（2026-10-03 修）。
        chars.value = Array.isArray(r) ? r : ((r && (r.characters || r.items)) || []);
  } catch (e) { chars.value = []; }
}

function onKindChange() {
  // 换类型时把细分重置成该类别的合理默认，避免把角色名带进辅助、或反之
  picked.value = isAssist.value ? "其它辅助" : "";
}

async function save() {
  if (!target.value) return;
  busy.value = true;
  try {
    // ① 先定类型（服装 / 辅助）—— 后端写 `kind`
    const k = await call("set_mod_kind", target.value.id, kind.value);
    if (k && k.ok === false) {
      await showAlert("设定失败", k.message || "未知原因");
      return;
    }
    // ② 再定细分：辅助 ⇒ 写分组；服装 ⇒ 写角色
    if (isAssist.value) {
      const r = await call("set_mod_group", target.value.id, String(picked.value || "其它辅助"));
      if (r && r.ok === false) { await showAlert("设定失败", r.message || "未知原因"); return; }
      showToast(`已归到辅助 ·「${picked.value}」`, "success");
    } else {
      const r = await call("set_mod_character", target.value.id, String(picked.value || ""));
      if (r && r.ok === false) { await showAlert("设定失败", r.message || "未知原因"); return; }
      showToast(picked.value ? `已归到服装 ·「${picked.value}」` : "已设为未分类（不参与同角色互斥）", "success");
    }
    target.value = null;
  } catch (e) { /* call 已弹窗 */ } finally {
    busy.value = false;
  }
}

defineExpose({ openFor });
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center" style="background: rgba(0,0,0,.45)">
    <div class="card w-[min(460px,94vw)] shadow-lg" style="background: var(--surface)">
      <div class="card-head">「{{ target.name }}」归到哪一类？</div>
      <div class="card-body space-y-3">
        <label class="block">
          <span class="text-xs" style="color: var(--text-muted)">① 类型</span>
          <select v-model="kind" class="field w-full mt-1" @change="onKindChange">
            <option value="character">服装 Mod（要选角色，参与同角色互斥）</option>
            <option value="assist">辅助 Mod（加载页 / 壁纸 / 功能类）</option>
          </select>
        </label>

        <label class="block">
          <span class="text-xs" style="color: var(--text-muted)">
            ② {{ isAssist ? "细分（分组）" : "细分（角色）" }}
          </span>
          <select v-if="isAssist" v-model="picked" class="field w-full mt-1">
            <option v-for="g in ASSIST_GROUPS" :key="g" :value="g">{{ g }}</option>
          </select>
          <select v-else v-model="picked" class="field w-full mt-1">
            <option value="">（未分类 —— 不参与同角色互斥）</option>
            <option v-for="name in chars" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>

        <p class="text-xs" style="color: var(--text-muted)">
          <template v-if="isAssist">
            辅助 Mod 按**分组**归类，同组可以同时开多个（加载页与壁纸类互斥，只保留一个）。
          </template>
          <template v-else>
            选一个角色后，同一个角色的其它 Mod 会自动取消勾选（防止两个同角色 Mod 同时生效把游戏搞崩）。
            <b>不选角色（未分类）也可以</b>。
          </template>
        </p>
      </div>
      <div class="px-4 py-3 flex justify-end gap-2 border-t" style="border-color: var(--border)">
        <Btn @click="target = null">取消</Btn>
        <Btn variant="primary" :disabled="busy" @click="save">保存</Btn>
      </div>
    </div>
  </div>
</template>
