<script setup lang="ts">
const props = defineProps<{ modelValue: string; value: string; label: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
function moveWithinGroup(event: KeyboardEvent, step: number) {
  const button = event.currentTarget as HTMLButtonElement
  const group = button.closest<HTMLElement>('[role="radiogroup"]')
  const choices = group ? Array.from(group.querySelectorAll<HTMLButtonElement>('button[role="radio"]:not(:disabled)')) : []
  const index = choices.indexOf(button)
  if (index < 0 || !choices.length) return
  event.preventDefault()
  const next = choices[(index + step + choices.length) % choices.length]
  next.focus()
  next.click()
}
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowDown' || event.key === 'ArrowRight') moveWithinGroup(event, 1)
  if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') moveWithinGroup(event, -1)
}
</script>
<template><label><button class="yk-radio" type="button" role="radio" :disabled="disabled" :aria-disabled="disabled || undefined" :aria-checked="modelValue === value" :aria-label="label" :data-checked="modelValue === value" @click="emit('update:modelValue', value)" @keydown="onKeydown"></button> {{ label }}</label></template>
