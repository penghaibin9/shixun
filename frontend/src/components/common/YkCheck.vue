<script setup lang="ts">
const props = defineProps<{ modelValue: boolean; label?: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
function toggle() { if (!props.disabled) emit('update:modelValue', !props.modelValue) }
</script>
<template><label><button class="yk-check" type="button" role="checkbox" :disabled="disabled" :aria-disabled="disabled || undefined" :aria-checked="modelValue" :aria-label="label || '复选框'" :data-checked="modelValue" @click="toggle">{{ modelValue ? '✓' : '' }}</button><span v-if="label"> {{ label }}</span></label></template>
