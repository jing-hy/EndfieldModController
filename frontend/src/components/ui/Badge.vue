<!-- SPDX-License-Identifier: AGPL-3.0-only -->
<script setup>
defineProps({ tone: { type: String, default: "muted" } });
</script>
<template><span :class="['badge', `badge-${tone}`]"><slot /></span></template>
