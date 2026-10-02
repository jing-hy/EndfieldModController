<script setup>
defineProps({ modelValue: [String, Number], placeholder: { type: String, default: "" }, rows: { type: Number, default: 0 } });
const emit = defineEmits(["update:modelValue"]);
</script>
<template>
  <textarea v-if="rows" class="field" :rows="rows" :placeholder="placeholder"
            :value="modelValue" @input="emit('update:modelValue', $event.target.value)"></textarea>
  <input v-else class="field" :placeholder="placeholder"
         :value="modelValue" @input="emit('update:modelValue', $event.target.value)" />
</template>
