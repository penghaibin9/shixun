<script setup lang="ts">
const navigation = [
  { to: '/teacher-dashboard', label: '教师工作台' },
  { to: '/student-home', label: '学生首页' },
  { to: '/lifecycle', label: '教学闭环' },
  { to: '/teacher-students', label: '学生管理' },
  { to: '/courses', label: '课程总览' },
  { to: '/attendance-management', label: '签到管理' },
  { to: '/teacher-assignments', label: '作业与测验' },
  { to: '/student-course', label: '我的课程' },
  { to: '/student-attendance', label: '课堂签到' },
  { to: '/student-quiz', label: '学生作业与测验' },
  { to: '/handoff', label: '协作交接' },
]
</script>
<template>
  <div class="app-shell">
    <aside class="side-nav"><strong>跃科网络空间安全实训平台</strong><nav><RouterLink v-for="item in navigation" :key="item.to" :to="item.to">{{ item.label }}</RouterLink></nav></aside>
    <main><header class="topbar"><span>数据安全技术基础</span><span class="role-badge">当前为验收视角</span></header><section class="page-content"><slot /></section></main>
  </div>
</template>
