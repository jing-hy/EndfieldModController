<script setup>
// 冲突处理弹窗（对应旧 web/app.js 的 showConflictResolveModal）。
// 用户 2026-10-01 要求：「每组冲突单独下拉框」，选要保留的；
// 「发现 mod 冲突风险应该先去清理才是右边的橙色主选项」—— 所以主按钮在右、
// "仍然继续"在最左且是次要样式。
import { ref } from "vue";

defineProps({ groups: { type: Array, default: () => [] } });
const emit = defineEmits(["resolve", "cancel"]);
const picked = ref({});   // 组序号 -> 要保留的 mod id
</script>

<template>
  <div class="fixed inset-0 z-[60] flex items-center justify-center" style="background: rgba(0,0,0,.45)">
    <div class="card w-[min(640px,92vw)] shadow-lg">
      <div class="card-head">发现 Mod 资源冲突</div>
      <div class="card-body space-y-3 overflow-auto" style="max-height: 58vh">
        <p class="text-sm leading-6" style="color: var(--text-muted)">
          下面每组里的 Mod 会互相覆盖同一批资源，同时生效常常让游戏崩。
          每组选一个**要保留的**，其余会被取消勾选。
          <b>只改勾选，不动你的 Mod 库</b>（随时可以再勾回来）。
        </p>
        <div v-for="(g, i) in groups" :key="i" class="rounded-lg border p-3" style="border-color: var(--border)">
          <div class="text-xs mb-2" style="color: var(--text-muted)">
            第 {{ i + 1 }} 组 · {{ (g.mods || []).length }} 个 Mod{{ g.group ? ' · ' + g.group : '' }}
          </div>
          <select class="field" v-model="picked[i]">
            <option value="">— 保持现状（都留着）—</option>
            <option v-for="m in (g.mods || [])" :key="m.id" :value="String(m.id)">
              {{ m.name || m.id }}
            </option>
          </select>
          <div v-if="g.reason" class="text-xs mt-2" style="color: var(--text-muted)">{{ g.reason }}</div>
        </div>
      </div>
      <div class="px-4 py-3 flex justify-end gap-2 border-t" style="border-color: var(--border)">
        <button class="btn btn-secondary" @click="emit('cancel')">仍然继续</button>
        <button class="btn btn-primary" @click="emit('resolve', Object.values(picked).filter(Boolean))">
          清理冲突
        </button>
      </div>
    </div>
  </div>
</template>
