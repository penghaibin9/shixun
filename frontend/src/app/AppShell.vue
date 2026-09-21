<script setup lang="ts">
const navigation = [
  { to: '/teacher-dashboard', label: '教师工作台' },
  { to: '/student-home', label: '学生首页' },
  { to: '/lifecycle', label: '教学闭环' },
  { to: '/handoff', label: '协作交接' },
  { to: '/teacher-grades', label: '成绩管理' },
  { to: '/analytics', label: '学情分析' },
  { to: '/archive', label: '课程归档' },
  { to: '/student-score', label: '我的成绩' },
  { to: '/admin-audit', label: '审计日志' },
]
</script>
<template>
  <div class="app-shell">
    <aside class="side-nav"><strong>跃科网络空间安全实训平台</strong><nav><RouterLink v-for="item in navigation" :key="item.to" :to="item.to">{{ item.label }}</RouterLink></nav></aside>
    <main><header class="topbar"><span>数据安全技术基础</span><span class="role-badge">当前为验收视角</span></header><section class="page-content"><slot /></section></main>
  </div>
</template>
