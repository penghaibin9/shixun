<script setup lang="ts">
const props = defineProps<{ modelValue: string; value: string; label: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
</script>
<template><label><button class="yk-radio" type="button" role="radio" :disabled="disabled" :aria-checked="modelValue === value" :data-checked="modelValue === value" @click="emit('update:modelValue', value)"></button> {{ label }}</label></template>
