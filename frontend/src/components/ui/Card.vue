<script setup>
// 卡片：标题栏右侧留一个插槽（放 badge / 小按钮），子内容进默认插槽。
defineProps({
  title: { type: String, default: "" },
  sub: { type: String, default: "" },
});
</script>
<template>
  <section class="card">
    <div v-if="title" class="card-head flex items-center justify-between gap-3">
      <span class="min-w-0 truncate">{{ title }}</span>
      <span class="flex items-center gap-2 shrink-0">
        <span v-if="sub" class="text-xs font-normal" style="color: var(--text-muted)">{{ sub }}</span>
        <slot name="badge" />
      </span>
    </div>
    <div class="card-body"><slot /></div>
  </section>
</template>
