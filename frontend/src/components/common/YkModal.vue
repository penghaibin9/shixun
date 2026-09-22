<script setup lang="ts">
import { ref, useId } from 'vue'
import { useDialogFocus } from './useDialogFocus'

const props = defineProps<{ open: boolean; title: string }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLElement | null>(null)
const closeButton = ref<HTMLElement | null>(null)
const titleId = `yk-modal-${useId()}-title`
const { onKeydown } = useDialogFocus(() => props.open, dialog, closeButton, () => emit('close'))
</script>
<template><div v-if="open" class="yk-modal-mask" @click.self="emit('close')"><section ref="dialog" class="yk-modal" role="dialog" aria-modal="true" tabindex="-1" :aria-label="title" :aria-labelledby="titleId" @keydown="onKeydown"><header class="page-header"><h2 :id="titleId">{{ title }}</h2><button ref="closeButton" class="yk-button" type="button" aria-label="关闭" @click="emit('close')">关闭</button></header><slot /></section></div></template>
