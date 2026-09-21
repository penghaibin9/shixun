<script setup lang="ts">
import YkPageHeader from '../../components/common/YkPageHeader.vue'
const steps = ['创建课程', '建班/导学生', '备课', '签到', '理论教学', '发布实验', '学生实验', '作业测验', '自动成绩', '学情分析', '课程归档']
</script>
<template><YkPageHeader title="完整教学闭环" description="固定为 11 步；每步由对应业务线提供真实状态。" /><ol class="card"><li v-for="step in steps" :key="step" style="padding:7px">{{ step }} <span class="muted">— 待业务模块接入</span></li></ol></template>
