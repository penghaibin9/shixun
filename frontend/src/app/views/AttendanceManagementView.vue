<script setup lang="ts">
import { onMounted, ref } from 'vue'
import YkSelect from '../../components/common/YkSelect.vue'
import { api, download, type ApiError } from '../api'

type Summary = { task_id: string; lesson: string | null; task_type: string; expected: number; present: number; late: number; absent: number; status: string }

const taskType = ref('CLASSROOM')
const taskId = ref(localStorage.getItem('yk-attendance-id') || '')
const signUrl = ref('')
const summaries = ref<Summary[]>([])
const message = ref('')
const options = [{ value: 'CLASSROOM', label: '课堂签到' }, { value: 'LAB', label: '实验签到' }, { value: 'ONLINE_ASSIGNMENT', label: '在线作业签到' }, { value: 'EXAM', label: '考试签到' }]
const typeLabels: Record<string, string> = Object.fromEntries(options.map(option => [option.value, option.label]))
const statusLabels: Record<string, string> = { DRAFT: '草稿', PUBLISHED: '进行中', CLOSED: '已关闭' }

async function refresh() {
  if (localStorage.getItem('yk-class-id')) summaries.value = (await api<{ items: Summary[] }>('/api/v1/attendance/section-summary')).items
}

async function publish() {
  try {
    const start = new Date(Date.now() - 60000)
    const end = new Date(Date.now() + 1800000)
    const created = await api<{ task_id: string }>('/api/v1/attendance/tasks', { method: 'POST', body: JSON.stringify({ course_id: localStorage.getItem('yk-course-id'), class_id: localStorage.getItem('yk-class-id'), task_type: taskType.value, title: 'RSA 数字签名课堂签到', starts_at: start.toISOString().replace('Z', ''), expires_at: end.toISOString().replace('Z', '') }) })
    const result = await api<{ sign_url: string }>(`/api/v1/attendance/tasks/${created.task_id}/publish`, { method: 'POST' })
    taskId.value = created.task_id
    signUrl.value = new URL(result.sign_url, window.location.origin).toString()
    localStorage.setItem('yk-attendance-id', created.task_id)
    localStorage.removeItem('yk-sign-token')
    message.value = '签到已发布'
    await refresh()
  } catch (error) {
    message.value = (error as ApiError).message
  }
}

async function closeTask() {
  await api(`/api/v1/attendance/tasks/${taskId.value}/close`, { method: 'POST' })
  message.value = '签到已关闭'
  await refresh()
}

async function exportXlsx() {
  const blob = await download(`/api/v1/attendance/${taskId.value}/export.xlsx`)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'attendance-records.xlsx'
  anchor.click()
  URL.revokeObjectURL(url)
}

async function copyLink() {
  if (signUrl.value) await window.navigator.clipboard?.writeText(signUrl.value)
}

onMounted(refresh)
</script>

<template>
  <div>
    <div class="hero"><div><h1>签到管理</h1><p>支持课堂、实验、在线作业和考试签到，实时查看并导出结果。</p></div><div class="actions"><button class="yk-button" @click="refresh">刷新结果</button><button class="yk-button primary" @click="publish">发布签到</button></div></div>
    <div class="card form-grid"><label class="yk-field"><span>签到类型</span><YkSelect v-model="taskType" :options="options"/></label><div class="yk-field"><span>有效时间</span><div class="input">30 分钟</div></div></div>
    <p v-if="message" data-testid="attendance-message" class="status-ok">{{ message }}</p>
    <div v-if="signUrl" class="card" style="margin-top:14px"><div class="row-between"><b>学生签到链接</b><div class="actions"><button class="yk-button" @click="copyLink">复制签到链接</button><button class="yk-button danger" @click="closeTask">关闭签到</button><button class="yk-button" @click="exportXlsx">导出 XLSX</button></div></div><a class="link-box" data-testid="attendance-link" :href="signUrl">{{ signUrl }}</a></div>
    <div v-if="summaries[0]" class="grid grid-4" style="margin-top:14px"><div class="card kpi"><span>应到</span><b>{{ summaries[0].expected }}</b></div><div class="card kpi"><span>实到</span><b>{{ summaries[0].present }}</b></div><div class="card kpi"><span>迟到</span><b>{{ summaries[0].late }}</b></div><div class="card kpi"><span>未到</span><b>{{ summaries[0].absent }}</b></div></div>
    <section class="card" style="margin-top:14px"><h3>按小节签到台账</h3><table class="data-table"><thead><tr><th>小节</th><th>类型</th><th>应到</th><th>实到</th><th>迟到</th><th>缺勤</th><th>状态</th></tr></thead><tbody><tr v-for="row in summaries" :key="row.task_id"><td>{{ row.lesson||'当前课时' }}</td><td>{{ typeLabels[row.task_type] || '未知类型' }}</td><td>{{ row.expected }}</td><td>{{ row.present }}</td><td>{{ row.late }}</td><td>{{ row.absent }}</td><td><span class="badge">{{ statusLabels[row.status] || '未知状态' }}</span></td></tr></tbody></table></section>
  </div>
</template>
