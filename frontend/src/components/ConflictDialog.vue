<script setup>
// 冲突处理弹窗（对应旧 web/app.js 的 showConflictResolveModal）。
// 用户 2026-10-01 要求：「每组冲突单独下拉框」，选要保留的；
// 「发现 mod 冲突风险应该先去清理才是右边的橙色主选项」—— 所以主按钮在右、
// "仍然继续"在最左且是次要样式。
import { ref, watch } from "vue";

const props = defineProps({ groups: { type: Array, default: () => [] } });
const emit = defineEmits(["resolve", "cancel"]);
// 组序号 -> 要保留的 mod id。
// ⚠️ 必须把每组显式初始化成 ""：留 undefined 时 <select> 不匹配任何 <option>，
// 界面上就是**一个空白下拉框**（用户根本不知道能不能选"都不动"）。
// 资源槽位名 → 用户能懂的说法（评审：直接把 head/body/weapon 这种内部枚举摆给用户看不懂）
const SLOT_LABELS = {
  head: "头部", body: "身体", weapon: "武器", coat: "外套", panties: "内裤",
  mask: "面罩", nudity: "裸体", skirt: "裙子", hair: "头发", face: "脸",
  leg: "腿部", arm: "手臂", shoe: "鞋子", tail: "尾巴", ear: "耳朵",
};
// ⚠️ 后端 `resolve_mod_conflicts(keep)` 的语义是"**没被 keep 的冲突 Mod 一律取消勾选**"。
// 所以"暂不处理"的组，必须把**该组所有 Mod** 都放进 keep —— 否则用户选了"都保持启用"，
// 实际结果是这一组被全部停用（2026-10-03 多角度审查抓到的真 bug）。
function keepList() {
  const keep = [];
  props.groups.forEach((g, i) => {
    const chosen = picked.value[i];
    const mods = g.mods || [];
    if (chosen) {
      keep.push(String(chosen));
    } else {
      for (const m of mods) keep.push(String(m.id));
    }
  });
  return keep;
}

function slotLabel(name) {
  if (!name) return "";
  return SLOT_LABELS[String(name).toLowerCase()] || String(name);
}

const picked = ref({});
watch(
  () => props.groups,
  (groups) => {
    const next = {};
    (groups || []).forEach((_, i) => { next[i] = ""; });
    picked.value = next;
  },
  { immediate: true },
);
</script>

<template>
  <div class="fixed inset-0 z-[60] flex items-center justify-center" style="background: rgba(0,0,0,.45)">
    <div class="card w-[min(640px,92vw)] shadow-lg">
      <div class="card-head">发现 Mod 资源冲突</div>
      <div class="card-body space-y-3 overflow-auto" style="max-height: 56vh; padding-bottom: 8px">
        <p class="text-sm leading-6" style="color: var(--text-muted)">
          下面每组里的 Mod 会互相覆盖同一批资源，同时生效常常让游戏崩。
          每组选一个<b>要保留的</b>，该组其余 Mod 会被取消勾选。
          <b>只改勾选，不删任何文件、不动你的 Mod 库</b>（随时可以再勾回来）。
        </p>
        <div v-for="(g, i) in groups" :key="i" class="rounded-lg border p-3" style="border-color: var(--border)">
          <div class="text-xs mb-2" style="color: var(--text-muted)">
            第 {{ i + 1 }} 组{{ slotLabel(g.group) ? " · " + slotLabel(g.group) : "" }} · 共 {{ (g.mods || []).length }} 个 Mod
          </div>
          <select class="field" v-model="picked[i]">
            <option value="">
              暂不处理：这 {{ (g.mods || []).length }} 个 Mod 都保持启用
            </option>
            <option v-for="m in (g.mods || [])" :key="m.id" :value="String(m.id)">
              保留「{{ m.name || m.id }}」，停用该组其他 {{ (g.mods || []).length - 1 }} 个
            </option>
          </select>
          <div v-if="g.reason" class="text-xs mt-2" style="color: var(--text-muted)">{{ g.reason }}</div>
        </div>
      </div>
      <div class="px-4 py-3 border-t" style="border-color: var(--border)">
        <div class="flex items-center justify-between gap-3">
          <span class="text-xs" style="color: var(--text-muted)">
            不会删除 Mod 文件，只调整"启用哪些"。整理完记得点「生成控制器」。
          </span>
          <span class="flex gap-2 shrink-0">
            <button class="btn btn-secondary" @click="emit('cancel')">暂不处理，继续</button>
            <button class="btn btn-primary" @click="emit('resolve', keepList())">
              应用选择并停用其他
            </button>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
