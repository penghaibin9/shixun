<script setup lang="ts">
defineProps<{ open: boolean; title: string }>()
const emit = defineEmits<{ close: [] }>()
</script>
<template><div v-if="open" class="yk-modal-mask" role="presentation" @click.self="emit('close')"><section class="yk-modal" role="dialog" aria-modal="true" :aria-label="title"><header class="page-header"><h2>{{ title }}</h2><button class="yk-button" type="button" aria-label="关闭" @click="emit('close')">关闭</button></header><slot /></section></div></template>
