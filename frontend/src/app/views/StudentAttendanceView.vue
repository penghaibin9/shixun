<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, type ApiError } from '../api'

type AttendanceLink = { task_id: string; title: string; task_type: string; starts_at: string; expires_at: string; status: string }

const route = useRoute()
const token = computed(() => typeof route.params.token === 'string' ? route.params.token : '')
const task = ref<AttendanceLink>()
const message = ref('')
const signed = ref(false)
const typeLabels: Record<string, string> = { CLASSROOM: '课堂签到', LAB: '实验签到', ONLINE_ASSIGNMENT: '在线作业签到', EXAM: '考试签到' }

async function load() {
  if (!token.value) {
    message.value = '请打开教师提供的签到链接'
    return
  }
  try {
    task.value = await api<AttendanceLink>(`/api/v1/attendance/sign-links/${encodeURIComponent(token.value)}`, {}, 'student')
  } catch (error) {
    message.value = (error as ApiError).message
  }
}

async function sign() {
  if (!token.value) return
  try {
    await api(`/api/v1/attendance/sign-links/${encodeURIComponent(token.value)}/sign`, { method: 'POST' }, 'student')
    signed.value = true
    message.value = '签到成功'
  } catch (error) {
    message.value = (error as ApiError).message
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="hero"><div><h1>课堂签到</h1><p>使用教师提供的不可预测链接完成签到，链接可在自己的浏览器或设备中直接打开。</p></div></div>
    <section class="card" style="max-width:700px">
      <div class="row-between"><div><span class="badge" :class="signed ? 'status-ok' : ''">{{ message || (task ? '等待签到' : '正在读取签到任务…') }}</span><h2>{{ task?.title || '课堂签到' }}</h2></div><b>{{ task ? typeLabels[task.task_type] || '签到' : '' }}</b></div>
      <p v-if="task" class="muted">有效期至：{{ new Date(task.expires_at).toLocaleString('zh-CN') }}</p>
      <button class="yk-button primary" style="width:100%" :disabled="!task || task.status !== 'PUBLISHED' || signed" @click="sign">{{ signed ? '已签到' : '立即签到' }}</button>
    </section>
  </div>
</template>
