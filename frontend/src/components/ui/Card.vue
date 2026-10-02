<script setup>
defineProps({ title: { type: String, default: "" } });
</script>
<template>
  <section class="card">
    <div v-if="title" class="card-head">{{ title }}</div>
    <div class="card-body"><slot /></div>
  </section>
</template>
