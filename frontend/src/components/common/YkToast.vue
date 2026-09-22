<script setup lang="ts">
defineProps<{ messages: { id: string; text: string }[] }>()
</script>
<template><div class="toast-region" role="status" aria-live="polite" aria-atomic="true"><div v-for="message in messages" :key="message.id" class="toast">{{ message.text }}</div></div></template>
