<script setup>
defineProps({ variant: { type: String, default: "secondary" }, size: { type: String, default: "md" }, disabled: Boolean });
</script>
<template>
  <button :class="['btn', `btn-${variant}`, size !== 'md' ? `btn-${size}` : '']" :disabled="disabled">
    <slot />
  </button>
</template>
