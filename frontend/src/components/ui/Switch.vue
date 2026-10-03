<script setup>
defineProps({ modelValue: Boolean });
const emit = defineEmits(["update:modelValue"]);
</script>
<template>
  <button role="switch" :aria-checked="String(!!modelValue)" class="switch" :style="{ background: modelValue ? 'var(--accent)' : 'var(--border-strong)' }"
          @click="emit('update:modelValue', !modelValue)">
    <span class="switch-knob" :style="{ left: modelValue ? '21px' : '3px' }"></span>
  </button>
</template>
