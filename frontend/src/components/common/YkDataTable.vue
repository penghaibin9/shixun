<script setup lang="ts" generic="T extends Record<string, unknown>">
defineProps<{ columns: { key: keyof T; label: string }[]; rows: T[] }>()
</script>
<template><table class="data-table"><thead><tr><th v-for="column in columns" :key="String(column.key)">{{ column.label }}</th></tr></thead><tbody><tr v-if="!rows.length"><td :colspan="columns.length" class="muted">暂无数据</td></tr><tr v-for="(row, index) in rows" :key="index"><td v-for="column in columns" :key="String(column.key)">{{ row[column.key] }}</td></tr></tbody></table></template>
