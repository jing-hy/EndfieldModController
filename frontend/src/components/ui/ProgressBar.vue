<script setup>
defineProps({ value: Number, max: { type: Number, default: 100 }, text: { type: String, default: "" } });
</script>
<template>
  <div>
    <div v-if="text" class="flex items-center justify-between text-xs mb-1.5">
      <span class="text-ink-muted">{{ text }}</span>
    </div>
    <div class="h-1.5 rounded-full overflow-hidden" :style="{ background: 'var(--surface-2)', border: '1px solid var(--border)' }">
      <div class="h-full transition-all" :style="{ width: Math.min(100, Math.max(0, (value / max) * 100)) + '%', background: 'var(--accent)' }"></div>
    </div>
  </div>
</template>
