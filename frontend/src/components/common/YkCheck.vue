<script setup lang="ts">
const props = defineProps<{ modelValue: boolean; label?: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
function toggle() { if (!props.disabled) emit('update:modelValue', !props.modelValue) }
</script>
<template><label><button class="yk-check" type="button" role="checkbox" :disabled="disabled" :aria-checked="modelValue" :data-checked="modelValue" @click="toggle">{{ modelValue ? '✓' : '' }}</button><span v-if="label"> {{ label }}</span></label></template>
