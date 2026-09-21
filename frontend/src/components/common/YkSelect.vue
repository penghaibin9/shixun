<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
type Option = { label: string; value: string }
const props = defineProps<{ modelValue: string; options: Option[]; label?: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const open = ref(false)
const current = computed(() => props.options.find((option) => option.value === props.modelValue)?.label ?? '请选择')
function choose(value: string) { emit('update:modelValue', value); open.value = false }
function onKeydown(event: KeyboardEvent) { if (event.key === 'Escape') open.value = false; if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open.value = !open.value } }
function close() { open.value = false }
window.addEventListener('click', close)
onBeforeUnmount(() => window.removeEventListener('click', close))
</script>
<template><div class="yk-field"><label v-if="label">{{ label }}</label><div class="yk-select" @click.stop><button class="yk-select-trigger" type="button" :disabled="disabled" aria-haspopup="listbox" :aria-expanded="open" @click="open = !open" @keydown="onKeydown">{{ current }}</button><div v-if="open" class="yk-options" role="listbox"><button v-for="option in options" :key="option.value" class="yk-option" type="button" role="option" :aria-selected="option.value === modelValue" @click="choose(option.value)">{{ option.label }}</button></div></div></div></template>
