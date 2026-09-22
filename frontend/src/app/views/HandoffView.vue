<script setup lang="ts">
import { onMounted, ref } from 'vue'

import YkPageHeader from '../../components/common/YkPageHeader.vue'
import { getCurrentContext, type ApiError, type UserContext } from '../api'

const context = ref<UserContext | null>(null)
const loading = ref(true)
const errorMessage = ref('')
const roleLabel: Record<UserContext['role'], string> = { teacher: '教师', student: '学生', admin: '管理员' }

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
  <YkPageHeader title="协作交接" description="各业务线只通过冻结的接口、事件和数据所有权进行集成。">
    <template #actions><button class="yk-button" :disabled="loading" @click="load">刷新会话范围</button></template>
  </YkPageHeader>
  <p v-if="errorMessage" class="notice error-state" role="alert" data-testid="handoff-error">{{ errorMessage }}。当前页面不把未确认的会话视为可交接状态。</p>
  <section v-else-if="loading" class="state-panel" aria-live="polite">正在读取当前会话范围…</section>
  <section v-else-if="context" class="card" data-testid="handoff-context">
    <h2>当前可交接范围</h2>
    <dl class="handoff-facts">
      <div><dt>当前身份</dt><dd>{{ roleLabel[context.role] }}</dd></div>
      <div><dt>已授权课程</dt><dd>{{ context.course_ids.length }} 门</dd></div>
      <div><dt>已授权班级</dt><dd>{{ context.class_ids.length }} 个</dd></div>
      <div><dt>冻结接口版本</dt><dd>API v1</dd></div>
    </dl>
    <p class="muted">页面只显示服务端解析的当前会话范围；本地构建、原型浏览或目录检查不会在这里被标记为生产验收完成。</p>
  </section>
</template>

<style scoped>
.handoff-facts { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:14px 0; }
.handoff-facts div { padding:12px; border:1px solid var(--line); border-radius:9px; }
.handoff-facts dt { color:var(--muted); font-size:12px; }
.handoff-facts dd { margin:6px 0 0; font-weight:700; }
@media (max-width: 760px) { .handoff-facts { grid-template-columns:repeat(2,minmax(0,1fr)); } }
</style>
