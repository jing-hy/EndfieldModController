<script setup>
defineProps({ tone: { type: String, default: "muted" } });
</script>
<template><span :class="['badge', `badge-${tone}`]"><slot /></span></template>
