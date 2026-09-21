<script setup lang="ts">
const navigation = [
  { to: '/teacher-dashboard', label: '教师工作台' },
  { to: '/student-home', label: '学生首页' },
  { to: '/lifecycle', label: '教学闭环' },
  { to: '/labs', label: '实验总览' },
  { to: '/lab-templates', label: '实验模板库' },
  { to: '/course-knowledge', label: '知识点讲解图' },
  { to: '/lab-builder', label: '创建实验' },
  { to: '/handoff', label: '协作交接' },
  { to: '/admin/overview', label: '运行总览' },
  { to: '/admin/nodes', label: '计算节点' },
  { to: '/admin/images', label: '镜像仓库' },
  { to: '/admin/scheduler', label: '调度队列' },
  { to: '/admin/network', label: '网络隔离' },
  { to: '/admin/instances', label: '实例运维' },
  { to: '/admin/alerts', label: '告警中心' },
  { to: '/admin/recovery', label: '异常恢复' },
]
</script>
<template>
  <div class="app-shell">
    <aside class="side-nav"><strong>跃科网络空间安全实训平台</strong><nav><RouterLink v-for="item in navigation" :key="item.to" :to="item.to">{{ item.label }}</RouterLink></nav></aside>
    <main><header class="topbar"><span>数据安全技术基础</span><span class="role-badge">当前为验收视角</span></header><section class="page-content"><slot /></section></main>
  </div>
</template>
