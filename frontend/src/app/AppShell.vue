<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { getCurrentContext, type ApiError, type UserContext } from './api'

type Role = UserContext['role']
type NavigationItem = { to: string; label: string; roles: Role[] }

const navigation: NavigationItem[] = [
  { to: '/teacher-dashboard', label: '教师工作台', roles: ['teacher'] },
  { to: '/lab-live', label: '实验课堂', roles: ['teacher'] },
  { to: '/teacher-instances', label: '实验实例', roles: ['teacher'] },
  { to: '/teacher-logs', label: '教学日志', roles: ['teacher'] },
  { to: '/student-home', label: '学生首页', roles: ['student'] },
  { to: '/student-lab', label: '我的实验', roles: ['student'] },
  { to: '/student-log', label: '我的日志任务', roles: ['student'] },
  { to: '/lifecycle', label: '教学闭环', roles: ['teacher', 'student', 'admin'] },
  { to: '/teacher-students', label: '学生管理', roles: ['teacher'] },
  { to: '/courses', label: '课程总览', roles: ['teacher'] },
  { to: '/attendance-management', label: '签到管理', roles: ['teacher'] },
  { to: '/teacher-assignments', label: '作业与测验', roles: ['teacher'] },
  { to: '/student-course', label: '我的课程', roles: ['student'] },
  { to: '/student-attendance', label: '课堂签到', roles: ['student'] },
  { to: '/student-quiz', label: '学生作业与测验', roles: ['student'] },
  { to: '/labs', label: '实验总览', roles: ['teacher'] },
  { to: '/challenges', label: '挑战训练', roles: ['teacher', 'student'] },
  { to: '/content-library', label: '内容包中心', roles: ['teacher', 'admin'] },
  { to: '/lab-templates', label: '实验模板库', roles: ['teacher'] },
  { to: '/course-knowledge', label: '知识点讲解图', roles: ['teacher'] },
  { to: '/lab-builder', label: '创建实验', roles: ['teacher'] },
  { to: '/handoff', label: '协作交接', roles: ['teacher', 'student', 'admin'] },
  { to: '/admin/overview', label: '运行总览', roles: ['admin'] },
  { to: '/admin/nodes', label: '计算节点', roles: ['admin'] },
  { to: '/admin/images', label: '镜像仓库', roles: ['admin'] },
  { to: '/admin/scheduler', label: '调度队列', roles: ['admin'] },
  { to: '/admin/network', label: '网络隔离', roles: ['admin'] },
  { to: '/admin/instances', label: '实例运维', roles: ['admin'] },
  { to: '/admin/alerts', label: '告警中心', roles: ['admin'] },
  { to: '/admin/recovery', label: '异常恢复', roles: ['admin'] },
  { to: '/teacher-grades', label: '成绩管理', roles: ['teacher'] },
  { to: '/analytics', label: '学情分析', roles: ['teacher'] },
  { to: '/archive', label: '课程归档', roles: ['teacher'] },
  { to: '/student-score', label: '我的成绩', roles: ['student'] },
  { to: '/admin-audit', label: '审计日志', roles: ['admin'] },
]

const resourceNavigation: NavigationItem[] = [
  { to: '/resources', label: '资源总览', roles: ['teacher', 'admin'] },
  { to: '/course-blueprint', label: '课程蓝图', roles: ['teacher', 'admin'] },
  { to: '/course-theory', label: '理论课时', roles: ['teacher', 'admin'] },
  { to: '/course-lab-lessons', label: '实验课时', roles: ['teacher', 'admin'] },
  { to: '/course-ppt', label: 'PPT / 讲义', roles: ['teacher', 'admin'] },
  { to: '/course-video', label: '视频中心', roles: ['teacher', 'admin'] },
  { to: '/course-questions', label: '题库中心', roles: ['teacher', 'admin'] },
  { to: '/course-procurement', label: '采购条款映射', roles: ['teacher', 'admin'] },
  { to: '/course-resource-audit', label: '完整性审计', roles: ['teacher', 'admin'] },
  { to: '/course-delivery', label: '发布与交付', roles: ['teacher', 'admin'] },
]

const context = ref<UserContext | null>(null)
const loading = ref(true)
const errorMessage = ref('')
const selectedCourseName = ref(localStorage.getItem('yk-course-name') || '数据安全技术基础')

const roleLabel: Record<Role, string> = { teacher: '教师', student: '学生', admin: '管理员' }
const visibleNavigation = computed(() => context.value
  ? navigation.filter(item => item.roles.includes(context.value!.role))
  : navigation.filter(item => item.to === '/lifecycle' || item.to === '/handoff'))
const visibleResourceNavigation = computed(() => context.value
  ? resourceNavigation.filter(item => item.roles.includes(context.value!.role))
  : [])

function syncCourseName(event: Event) {
  const detail = (event as CustomEvent<string>).detail
  selectedCourseName.value = detail || localStorage.getItem('yk-course-name') || '数据安全技术基础'
}

async function loadContext() {
  loading.value = true
  errorMessage.value = ''
  try {
    context.value = await getCurrentContext()
  } catch (error) {
    context.value = null
    errorMessage.value = (error as ApiError).message || '未能确认当前会话身份'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  window.addEventListener('yk-course-changed', syncCourseName)
  loadContext()
})
onBeforeUnmount(() => window.removeEventListener('yk-course-changed', syncCourseName))
</script>

<template>
  <div class="app-shell">
    <aside class="side-nav">
      <strong>跃科网络空间安全实训平台</strong>
      <nav aria-label="主导航">
        <RouterLink v-for="item in visibleNavigation" :key="item.to" :to="item.to">{{ item.label }}</RouterLink>
        <template v-if="visibleResourceNavigation.length">
          <span class="nav-group">课程建设中心</span>
          <RouterLink v-for="item in visibleResourceNavigation" :key="item.to" :to="item.to">{{ item.label }}</RouterLink>
        </template>
      </nav>
    </aside>
    <main>
      <header class="topbar">
        <span>{{ selectedCourseName }}</span>
        <span v-if="loading" class="role-badge" aria-live="polite">正在确认当前会话…</span>
        <span v-else-if="context" class="role-badge" data-testid="app-shell-role">当前身份：{{ roleLabel[context.role] }}</span>
        <span v-else class="role-badge session-error" role="alert" data-testid="app-shell-session-error">未取得可信会话身份：{{ errorMessage }}</span>
        <button v-if="!loading && !context" class="yk-button" type="button" @click="loadContext">重新确认</button>
      </header>
      <section class="page-content"><slot /></section>
    </main>
  </div>
</template>

<style scoped>
.session-error { color: var(--danger); }
</style>
