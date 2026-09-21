<script setup lang="ts">
import YkPageHeader from '../../components/common/YkPageHeader.vue'
const cards = [{ label: '课程资源完整度', value: '—' }, { label: '实验模板', value: '—' }, { label: '运行实例', value: '—' }, { label: '教学闭环', value: '0 / 11' }]
</script>
<template><YkPageHeader title="教师工作台" description="课程、资源、实验和成绩将通过同一课程事实汇总展示。" /><div class="grid grid-4"><article v-for="card in cards" :key="card.label" class="card kpi"><span class="muted">{{ card.label }}</span><b>{{ card.value }}</b><small class="muted">等待业务模块接入</small></article></div><section class="card" style="margin-top:14px"><h2>当前教学流程</h2><p class="muted">公共壳已冻结；课程、签到、实验和成绩数据由各业务模块通过冻结接口接入。</p></section></template>
