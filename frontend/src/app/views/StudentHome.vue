<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import YkPageHeader from '../../components/common/YkPageHeader.vue'
import { api, type ApiError } from '../api'

type OpenAttendance = { task_id: string; title: string; expires_at: string }
type StudentLearningHome = { class_count: number; open_attendance: OpenAttendance[] }

const home = ref<StudentLearningHome>({ class_count: 0, open_attendance: [] })
const loading = ref(true)
const errorMessage = ref('')

const attendanceLabel = computed(() => home.value.open_attendance.length ? `待完成 ${home.value.open_attendance.length}` : '暂无待办')

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '截止时间待确认' : date.toLocaleString('zh-CN', { hour12: false })
}

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    home.value = await api<StudentLearningHome>('/api/v1/teaching/student-read-model', {}, 'student')
  } catch (error) {
    errorMessage.value = (error as ApiError).message || '学习首页数据读取失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <YkPageHeader title="学生首页" description="只展示当前学生本人已加入班级和已发布的学习任务。">
    <template #actions><button class="yk-button" :disabled="loading" data-testid="student-home-refresh" @click="load">刷新数据</button></template>
  </YkPageHeader>

  <p v-if="errorMessage" class="notice error-state" role="alert" data-testid="student-home-error">{{ errorMessage }}</p>
  <section v-else-if="loading" class="state-panel" aria-live="polite">正在读取我的学习任务…</section>
  <template v-else>
    <section class="card" data-testid="student-home-summary">
      <div class="section-head"><div><h2>我的学习概览</h2><p class="muted">数据由服务端按当前学生身份过滤，不显示其他学生的课程或任务。</p></div><span class="badge success">已读取</span></div>
      <div class="grid grid-2">
        <article class="card kpi"><span class="muted">已加入班级</span><b>{{ home.class_count }}</b><small class="muted">当前有效班级</small></article>
        <article class="card kpi"><span class="muted">课堂签到</span><b>{{ attendanceLabel }}</b><small class="muted">仅列出已发布任务</small></article>
      </div>
    </section>

    <section class="card" style="margin-top:14px">
      <div class="section-head"><h2>今天要完成</h2><span class="badge">实时任务</span></div>
      <div v-if="home.open_attendance.length" class="task-list">
        <RouterLink v-for="task in home.open_attendance" :key="task.task_id" to="/student-attendance" class="student-task" data-testid="student-home-attendance-task">
          <strong>{{ task.title }}</strong><span>请在 {{ formatTime(task.expires_at) }} 前完成课堂签到。</span><span aria-hidden="true">去签到 →</span>
        </RouterLink>
      </div>
      <p v-else class="muted" data-testid="student-home-empty">当前没有已发布的课堂签到任务。其他学习任务会在相应模块发布后显示。</p>
    </section>
  </template>
</template>

<style scoped>
.task-list { display:grid; gap:10px; }
.student-task { display:grid; grid-template-columns:1fr auto; gap:4px 12px; color:inherit; text-decoration:none; border:1px solid var(--line); border-radius:10px; padding:13px; }
.student-task:hover { border-color:var(--p); background:var(--p-soft); }
.student-task span { color:var(--muted); font-size:12px; }
.student-task span:last-child { grid-column:2; grid-row:1 / span 2; align-self:center; color:var(--p); font-weight:600; }
</style>
