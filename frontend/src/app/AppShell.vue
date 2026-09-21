<script setup lang="ts">
const navigation = [
  { to: '/teacher-dashboard', label: '教师工作台' },
  { to: '/student-home', label: '学生首页' },
  { to: '/lifecycle', label: '教学闭环' },
  { to: '/handoff', label: '协作交接' },
]
const resourceNavigation = [
  { to: '/resources', label: '资源总览' }, { to: '/course-blueprint', label: '课程蓝图' },
  { to: '/course-theory', label: '理论课时' }, { to: '/course-lab-lessons', label: '实验课时' },
  { to: '/course-ppt', label: 'PPT / 讲义' }, { to: '/course-video', label: '视频中心' },
  { to: '/course-questions', label: '题库中心' }, { to: '/course-procurement', label: '采购条款映射' },
  { to: '/course-resource-audit', label: '完整性审计' }, { to: '/course-delivery', label: '发布与交付' },
]
</script>
<template>
  <div class="app-shell">
    <aside class="side-nav"><strong>跃科网络空间安全实训平台</strong><nav><RouterLink v-for="item in navigation" :key="item.to" :to="item.to">{{ item.label }}</RouterLink><span class="nav-group">课程建设中心</span><RouterLink v-for="item in resourceNavigation" :key="item.to" :to="item.to">{{ item.label }}</RouterLink></nav></aside>
    <main><header class="topbar"><span>数据安全技术基础</span><span class="role-badge">当前为验收视角</span></header><section class="page-content"><slot /></section></main>
  </div>
</template>
