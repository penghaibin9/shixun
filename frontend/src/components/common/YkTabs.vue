<script setup lang="ts">
defineProps<{ modelValue: string; tabs: { label: string; value: string }[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
</script>
<template><div class="yk-tabs" role="tablist"><button v-for="tab in tabs" :key="tab.value" type="button" role="tab" :aria-selected="modelValue === tab.value" @click="emit('update:modelValue', tab.value)">{{ tab.label }}</button></div></template>
