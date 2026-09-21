<script setup lang="ts">
defineProps<{ messages: { id: string; text: string }[] }>()
</script>
<template><div class="toast-region" aria-live="polite"><div v-for="message in messages" :key="message.id" class="toast">{{ message.text }}</div></div></template>
