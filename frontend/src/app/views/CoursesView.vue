<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, download, fileIdempotencyKey, type ApiError } from '../api'

type Course = { course_id: string; name: string; term: string; status: string }
type ClassInfo = { class_id: string; name: string; term: string }
type Member = { student_id: string; student_number: string; student_name: string; status: string }
type ImportResult = { success_count: number; failure_count: number; duplicate_count: number; job_id: string }

const courses = ref<Course[]>([])
const classes = ref<ClassInfo[]>([])
const members = ref<Member[]>([])
const file = ref<File>()
const message = ref('')
const importResult = ref<ImportResult>()
const courseStatusLabels: Record<string, string> = { DRAFT: '草稿', ACTIVE: '进行中', ARCHIVED: '已归档' }

async function load() {
  const courseId = localStorage.getItem('yk-course-id')
  const classId = localStorage.getItem('yk-class-id')
  if (courseId) courses.value = (await api<{ items: Course[] }>('/api/v1/courses')).items
  if (classId) {
    classes.value = (await api<{ items: ClassInfo[] }>('/api/v1/classes')).items
    members.value = (await api<{ items: Member[] }>(`/api/v1/classes/${classId}/members?page=1&page_size=100`)).items
    if (members.value[0]) localStorage.setItem('yk-student-id', members.value[0].student_id)
  }
}

async function createCourse() {
  try {
    const item = await api<Course>('/api/v1/courses', { method: 'POST', body: JSON.stringify({ name: '数据安全技术基础', term: '2026 秋季', major: '网络空间安全', description: '围绕数据安全基础、加密、访问控制和安全治理开展教学。' }) })
    localStorage.setItem('yk-course-id', item.course_id)
    message.value = '课程已创建'
    await load()
  } catch (error) {
    message.value = (error as ApiError).message
  }
}

async function createClass() {
  const courseId = localStorage.getItem('yk-course-id')
  if (!courseId) return
  const item = await api<ClassInfo>('/api/v1/classes', { method: 'POST', body: JSON.stringify({ name: '网络安全 2301 班', term: '2026 秋季', course_id: courseId }) })
  localStorage.setItem('yk-class-id', item.class_id)
  message.value = '班级已创建'
  await load()
}

async function saveBlob(path: string, name: string) {
  const blob = await download(path)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}

async function getTemplate() {
  const id = localStorage.getItem('yk-class-id')
  if (id) await saveBlob(`/api/v1/classes/${id}/members/import-template`, 'student-import-template.xlsx')
}

async function importMembers() {
  const id = localStorage.getItem('yk-class-id')
  if (!id || !file.value) return
  const form = new FormData()
  form.append('file', file.value)
  const idempotencyKey = await fileIdempotencyKey('members', file.value)
  importResult.value = await api<ImportResult>(`/api/v1/classes/${id}/members/import`, { method: 'POST', body: form, headers: { 'Idempotency-Key': idempotencyKey } })
  localStorage.setItem('yk-import-job-id', importResult.value.job_id)
  await load()
  message.value = `成功 ${importResult.value.success_count} 人，失败 ${importResult.value.failure_count} 人`
}

async function downloadImportErrors() {
  if (importResult.value?.job_id) await saveBlob(`/api/v1/import-jobs/${importResult.value.job_id}/error-rows.xlsx`, 'student-import-errors.xlsx')
}

onMounted(load)
</script>

<template>
  <div>
    <div class="hero">
      <div><h1>课程中心</h1><p>课程、班级、章节、课时和学生名单统一维护。</p></div>
      <div class="actions"><button class="yk-button primary" @click="createCourse">＋ 新建课程</button><button class="yk-button" :disabled="!courses.length" @click="createClass">＋ 建班</button></div>
    </div>
    <p v-if="message" data-testid="message" class="status-ok">{{ message }}</p>
    <div class="grid grid-2">
      <article v-for="course in courses" :key="course.course_id" class="card"><span class="badge">{{ courseStatusLabels[course.status] || '未知状态' }}</span><h3>{{ course.name }}</h3><p class="muted">{{ course.term }} · 37 理论课时 · 12 实验课时</p></article>
      <article v-if="!courses.length" class="card muted">尚未创建课程</article>
    </div>
    <section class="card" style="margin-top:14px">
      <div class="section-head"><div><h3>建班 / 导入学生</h3><p class="muted">使用正式 XLSX（电子表格）模板，逐行校验并提供错误行文件。</p></div><span class="badge">{{ members.length }} 人</span></div>
      <div class="actions">
        <button class="yk-button" :disabled="!classes.length" @click="getTemplate">下载导入模板</button>
        <input aria-label="选择学生名单" type="file" accept=".xlsx" @change="file=($event.target as HTMLInputElement).files?.[0]">
        <button class="yk-button primary" :disabled="!file" @click="importMembers">导入学生</button>
        <button v-if="importResult?.failure_count" class="yk-button" data-testid="import-error-download" @click="downloadImportErrors">下载逐行错误文件</button>
      </div>
      <table class="data-table"><thead><tr><th>学号</th><th>姓名</th><th>课程状态</th></tr></thead><tbody><tr v-for="member in members" :key="member.student_id"><td>{{ member.student_number }}</td><td>{{ member.student_name }}</td><td><span class="badge">在读</span></td></tr><tr v-if="!members.length"><td colspan="3" class="muted">尚未导入学生</td></tr></tbody></table>
    </section>
  </div>
</template>
