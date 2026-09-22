<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useAttrs, useId } from 'vue'
type Option = { label: string; value: string }
const props = defineProps<{ modelValue: string; options: Option[]; label?: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
defineOptions({ inheritAttrs: false })
const attrs = useAttrs()
const open = ref(false)
const trigger = ref<HTMLButtonElement | null>(null)
const selectId = `yk-select-${useId()}`
const labelId = `${selectId}-label`
const current = computed(() => props.options.find((option) => option.value === props.modelValue)?.label ?? '请选择')
const accessibleLabel = computed(() => (typeof attrs['aria-label'] === 'string' ? attrs['aria-label'] : (props.label ? undefined : '选择选项')))
const selectedIndex = computed(() => Math.max(0, props.options.findIndex((option) => option.value === props.modelValue)))
function optionId(index: number) { return `${selectId}-option-${index}` }
function focusOption(index: number) { void nextTick(() => document.getElementById(optionId(index))?.focus()) }
function choose(value: string) {
  emit('update:modelValue', value)
  open.value = false
  void nextTick(() => trigger.value?.focus())
}
function openAt(index: number) {
  if (props.disabled || !props.options.length) return
  open.value = true
  focusOption(Math.max(0, Math.min(index, props.options.length - 1)))
}
function toggle() {
  if (props.disabled) return
  open.value = !open.value
}
function onTriggerKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { open.value = false; return }
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    toggle()
    return
  }
  if (event.key === 'ArrowDown') { event.preventDefault(); openAt(selectedIndex.value + 1); return }
  if (event.key === 'ArrowUp') { event.preventDefault(); openAt(selectedIndex.value - 1); return }
  if (event.key === 'Home') { event.preventDefault(); openAt(0); return }
  if (event.key === 'End') { event.preventDefault(); openAt(props.options.length - 1) }
}
function onOptionKeydown(event: KeyboardEvent, index: number) {
  if (event.key === 'Escape') {
    event.preventDefault()
    open.value = false
    trigger.value?.focus()
    return
  }
  if (event.key === 'Tab') { open.value = false; return }
  if (event.key === 'ArrowDown') { event.preventDefault(); focusOption((index + 1) % props.options.length); return }
  if (event.key === 'ArrowUp') { event.preventDefault(); focusOption((index - 1 + props.options.length) % props.options.length); return }
  if (event.key === 'Home') { event.preventDefault(); focusOption(0); return }
  if (event.key === 'End') { event.preventDefault(); focusOption(props.options.length - 1); return }
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(props.options[index].value) }
}
function close() { open.value = false }
window.addEventListener('click', close)
onBeforeUnmount(() => window.removeEventListener('click', close))
</script>
<template>
  <div class="yk-field">
    <label v-if="label" :id="labelId" :for="selectId">{{ label }}</label>
    <div class="yk-select" @click.stop>
      <button ref="trigger" v-bind="$attrs" :id="selectId" class="yk-select-trigger" type="button" :disabled="disabled" aria-haspopup="listbox" :aria-expanded="open" :aria-controls="open ? `${selectId}-options` : undefined" :aria-labelledby="label ? labelId : undefined" :aria-label="accessibleLabel" @click="toggle" @keydown="onTriggerKeydown">{{ current }}</button>
      <div v-if="open" :id="`${selectId}-options`" class="yk-options" role="listbox" :aria-labelledby="selectId">
        <button v-for="(option, index) in options" :id="optionId(index)" :key="option.value" class="yk-option" type="button" role="option" :aria-selected="option.value === modelValue" @click="choose(option.value)" @keydown="onOptionKeydown($event, index)">{{ option.label }}</button>
      </div>
    </div>
  </div>
</template>
