<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<script setup>
defineProps({ tone: { type: String, default: "muted" } });
</script>
<template><span :class="['badge', `badge-${tone}`]"><slot /></span></template>
