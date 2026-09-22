<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import YkPageHeader from '../../components/common/YkPageHeader.vue'
import { api, type ApiError } from '../api'

type TeachingDashboard = {
  course_count: number
  class_count: number
  student_count: number
  open_attendance_count: number
}

const dashboard = ref<TeachingDashboard>({ course_count: 0, class_count: 0, student_count: 0, open_attendance_count: 0 })
const loading = ref(true)
const errorMessage = ref('')

const cards = computed(() => [
  { label: '我的课程', value: dashboard.value.course_count, detail: '已授权课程' },
  { label: '授课班级', value: dashboard.value.class_count, detail: '已授权班级' },
  { label: '班级学生', value: dashboard.value.student_count, detail: '当前有效名单' },
  { label: '正在签到', value: dashboard.value.open_attendance_count, detail: '已发布签到任务' },
])

const nextActions = computed(() => {
  const snapshot = dashboard.value
  if (!snapshot.course_count) return [{ title: '创建课程', detail: '先建立课程事实，后续班级、资源与教学活动才能关联。', to: '/courses' }]
  if (!snapshot.class_count) return [{ title: '建立班级', detail: '为当前课程建立授课班级。', to: '/courses' }]
  if (!snapshot.student_count) return [{ title: '导入学生名单', detail: '使用已开户学生的名单模板导入，并处理逐行反馈。', to: '/teacher-students' }]
  if (!snapshot.open_attendance_count) return [{ title: '发布课堂签到', detail: '当前没有已发布签到任务。', to: '/attendance-management' }]
  return [{ title: '查看签到进展', detail: `当前有 ${snapshot.open_attendance_count} 个签到任务正在进行。`, to: '/attendance-management' }]
})

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    dashboard.value = await api<TeachingDashboard>('/api/v1/teaching/read-model')
  } catch (error) {
    errorMessage.value = (error as ApiError).message || '教学工作台数据读取失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <YkPageHeader title="教师工作台" description="仅汇总当前账号有权访问的课程、班级、学生名单和签到事实。">
    <template #actions><button class="yk-button" :disabled="loading" data-testid="teacher-dashboard-refresh" @click="load">刷新数据</button></template>
  </YkPageHeader>

  <p v-if="errorMessage" class="notice error-state" role="alert" data-testid="teacher-dashboard-error">{{ errorMessage }}</p>
  <section v-else-if="loading" class="state-panel" aria-live="polite">正在读取教学工作台数据…</section>
  <template v-else>
    <section class="card" data-testid="teacher-dashboard-summary">
      <div class="section-head"><div><h2>当前教学概览</h2><p class="muted">统计来自课程、班级、名单和签到的已授权读模型，不使用页面写死数据。</p></div><span class="badge success">已读取</span></div>
      <div class="grid grid-4">
        <article v-for="card in cards" :key="card.label" class="card kpi"><span class="muted">{{ card.label }}</span><b>{{ card.value }}</b><small class="muted">{{ card.detail }}</small></article>
      </div>
    </section>

    <div class="grid grid-2" style="margin-top:14px">
      <section class="card">
        <div class="section-head"><h2>现在可处理</h2><span class="badge">按真实状态排序</span></div>
        <RouterLink v-for="action in nextActions" :key="action.title" :to="action.to" class="dashboard-action" data-testid="teacher-dashboard-next-action">
          <strong>{{ action.title }}</strong><span>{{ action.detail }}</span><span aria-hidden="true">前往 →</span>
        </RouterLink>
      </section>
      <section class="card">
        <div class="section-head"><h2>事实范围</h2><span class="badge">权限隔离</span></div>
        <p class="muted">工作台以服务端解析的课程和班级范围为准，只汇总当前账号已获授权的教学事实。</p>
        <RouterLink class="yk-button primary" to="/lifecycle">查看教学闭环</RouterLink>
      </section>
    </div>
  </template>
</template>

<style scoped>
.dashboard-action { display:grid; grid-template-columns:1fr auto; gap:4px 12px; color:inherit; text-decoration:none; border:1px solid var(--line); border-radius:10px; padding:13px; margin-top:10px; }
.dashboard-action:hover { border-color:var(--p); background:var(--p-soft); }
.dashboard-action strong { font-size:14px; }
.dashboard-action span { color:var(--muted); font-size:12px; }
.dashboard-action span:last-child { grid-column:2; grid-row:1 / span 2; align-self:center; color:var(--p); font-weight:600; }
</style>
