<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import YkPageHeader from '../../components/common/YkPageHeader.vue'
import { getCurrentContext, type ApiError, type UserContext } from '../api'

type Role = UserContext['role']
type LifecycleStep = {
  title: string
  to: string
  roles: Role[]
  permissions: string[]
  detail: string
}

const steps: LifecycleStep[] = [
  { title: '创建课程', to: '/courses', roles: ['teacher'], permissions: ['teaching.course.write'], detail: '课程事实由课程服务维护。' },
  { title: '建班/导学生', to: '/teacher-students', roles: ['teacher'], permissions: ['teaching.members.import'], detail: '名单只可解析已有且启用的学生档案。' },
  { title: '备课', to: '/resources', roles: ['teacher', 'admin'], permissions: ['resources:read'], detail: '资源状态由课程资源服务返回。' },
  { title: '签到', to: '/attendance-management', roles: ['teacher'], permissions: ['teaching.attendance.write'], detail: '签到任务以教学服务记录为准。' },
  { title: '理论教学', to: '/course-theory', roles: ['teacher', 'admin'], permissions: ['resources:read'], detail: '理论课时资料由课程资源服务维护。' },
  { title: '发布实验', to: '/labs', roles: ['teacher'], permissions: ['labs.publish'], detail: '实验定义与发布状态由实验服务维护。' },
  { title: '学生实验', to: '/student-lab', roles: ['student'], permissions: ['classroom.lab.read'], detail: '学生仅能查看本人已获授权的实验。' },
  { title: '作业测验', to: '/student-quiz', roles: ['student'], permissions: ['teaching.quiz.submit'], detail: '提交与评分事实以服务端校验结果为准。' },
  { title: '自动成绩', to: '/teacher-grades', roles: ['teacher'], permissions: ['grading:read'], detail: '成绩册只使用已消费的评分事实。' },
  { title: '学情分析', to: '/analytics', roles: ['teacher'], permissions: ['analytics:class'], detail: '学情统计由成绩与实验事实生成。' },
  { title: '课程归档', to: '/archive', roles: ['teacher'], permissions: ['archives:read'], detail: '归档前置条件与清单由归档服务核验。' },
]

const context = ref<UserContext | null>(null)
const loading = ref(true)
const errorMessage = ref('')

const visibleSteps = computed(() => steps.map(step => ({
  ...step,
  accessible: Boolean(context.value)
    && step.roles.includes(context.value!.role)
    && step.permissions.every(permission => context.value!.permissions.includes(permission)),
})))

async function load() {
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

onMounted(load)
</script>

<template>
  <YkPageHeader title="完整教学闭环" description="展示 11 个流程入口与当前身份的授权范围；不把本页当作业务完成或验收结论。">
    <template #actions><button class="yk-button" :disabled="loading" @click="load">重新确认身份</button></template>
  </YkPageHeader>
  <p v-if="errorMessage" class="notice error-state" role="alert" data-testid="lifecycle-error">{{ errorMessage }}。无法据此判断任何业务步骤是否完成。</p>
  <section v-else-if="loading" class="state-panel" aria-live="polite">正在读取当前会话的授权范围…</section>
  <ol v-else class="card lifecycle-list" data-testid="lifecycle-list">
    <li v-for="step in visibleSteps" :key="step.title">
      <div><strong>{{ step.title }}</strong><p class="muted">{{ step.detail }}</p></div>
      <RouterLink v-if="step.accessible" class="yk-button" :to="step.to">当前身份可办理</RouterLink>
      <span v-else class="muted">不在当前身份授权范围</span>
    </li>
  </ol>
</template>

<style scoped>
.lifecycle-list { display:grid; gap:8px; margin:0; padding:14px; list-style-position:inside; }
.lifecycle-list li { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:10px; border:1px solid var(--line); border-radius:9px; }
.lifecycle-list p { margin:4px 0 0; }
@media (max-width: 640px) { .lifecycle-list li { align-items:flex-start; flex-direction:column; } }
</style>
