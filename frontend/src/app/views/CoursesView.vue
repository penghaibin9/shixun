<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, download, fileIdempotencyKey, type ApiError } from '../api'

type Course = { course_id: string; name: string; term: string; status: string; theory_lesson_count: number; lab_lesson_count: number }
type CourseCatalog = { catalog_key: string; name: string; theory_lessons: number; lab_lessons: number }
type ClassInfo = { class_id: string; name: string; term: string }
type Member = { student_id: string; student_number: string; student_name: string; status: string }
type ImportResult = { success_count: number; failure_count: number; duplicate_count: number; job_id: string }

const courses = ref<Course[]>([])
const catalogs = ref<CourseCatalog[]>([])
const selectedCatalogKey = ref('')
const classes = ref<ClassInfo[]>([])
const members = ref<Member[]>([])
const file = ref<File>()
const message = ref('')
const importResult = ref<ImportResult>()
const selectedCourseId = ref(localStorage.getItem('yk-course-id') || '')
const courseStatusLabels: Record<string, string> = { DRAFT: '草稿', ACTIVE: '进行中', ARCHIVED: '已归档' }

async function load() {
  const classId = localStorage.getItem('yk-class-id')
  const [courseResult, catalogResult] = await Promise.all([
    api<{ items: Course[] }>('/api/v1/courses'),
    api<{ items: CourseCatalog[] }>('/api/v1/course-catalogs'),
  ])
  courses.value = courseResult.items
  catalogs.value = catalogResult.items
  if (!catalogs.value.some(item => item.catalog_key === selectedCatalogKey.value)) {
    selectedCatalogKey.value = catalogs.value[0]?.catalog_key || ''
  }
  if (classId) {
    classes.value = (await api<{ items: ClassInfo[] }>('/api/v1/classes')).items
    members.value = (await api<{ items: Member[] }>(`/api/v1/classes/${classId}/members?page=1&page_size=100`)).items
    if (members.value[0]) localStorage.setItem('yk-student-id', members.value[0].student_id)
  }
}

function selectCourse(course: Course) {
  selectedCourseId.value = course.course_id
  localStorage.setItem('yk-course-id', course.course_id)
  localStorage.setItem('yk-course-name', course.name)
  window.dispatchEvent(new CustomEvent('yk-course-changed', { detail: course.name }))
  message.value = `已选择课程：${course.name}`
}

async function createCourse() {
  try {
    const catalog = catalogs.value.find(item => item.catalog_key === selectedCatalogKey.value)
    if (!catalog) {
      message.value = '请先选择课程模板'
      return
    }
    const description = `《${catalog.name}》课程模板，理论、实验、题库与实验定义按统一课程目录合同维护。`
    const item = await api<Course>('/api/v1/courses', {
      method: 'POST',
      body: JSON.stringify({
        name: catalog.name,
        term: '2026 秋季',
        major: '网络空间安全',
        description,
        catalog_key: catalog.catalog_key,
      }),
    })
    localStorage.setItem('yk-course-id', item.course_id)
    localStorage.setItem('yk-course-name', item.name)
    window.dispatchEvent(new CustomEvent('yk-course-changed', { detail: item.name }))
    selectedCourseId.value = item.course_id
    message.value = `已创建：${item.name}`
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
      <div class="actions"><button class="yk-button primary" :disabled="!catalogs.length" @click="createCourse">＋ 按模板新建课程</button><button class="yk-button" :disabled="!courses.length" @click="createClass">＋ 建班</button></div>
    </div>
    <p v-if="message" data-testid="message" class="status-ok">{{ message }}</p>
    <section class="card catalog-picker">
      <div class="section-head"><div><h3>课程模板</h3><p class="muted">选择模板后新建课程；已有课程不会被覆盖。</p></div></div>
      <div class="actions">
        <button v-for="catalog in catalogs" :key="catalog.catalog_key" type="button" class="yk-button" :class="{ primary: selectedCatalogKey === catalog.catalog_key }" :aria-pressed="selectedCatalogKey === catalog.catalog_key" @click="selectedCatalogKey = catalog.catalog_key">
          {{ catalog.name }} · {{ catalog.theory_lessons }}+{{ catalog.lab_lessons }} 课时
        </button>
      </div>
    </section>
    <div class="grid grid-2">
      <button v-for="course in courses" :key="course.course_id" type="button" class="card course-card" :class="{ selected: selectedCourseId === course.course_id }" :aria-pressed="selectedCourseId === course.course_id" :data-testid="`course-${course.course_id}`" @click="selectCourse(course)"><span class="badge">{{ courseStatusLabels[course.status] || '未知状态' }}</span><span v-if="selectedCourseId === course.course_id" class="badge selected-badge">当前课程</span><span class="course-title">{{ course.name }}</span><span class="muted">{{ course.term }} · {{ course.theory_lesson_count }} 理论课时 · {{ course.lab_lesson_count }} 实验课时</span></button>
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

<style scoped>
.course-card { color: inherit; font: inherit; text-align: left; cursor: pointer; }
.course-card.selected { border-color: var(--primary, #2563eb); box-shadow: 0 0 0 2px rgb(37 99 235 / 14%); }
.course-title { display: block; margin: 14px 0 8px; font-size: 1.1rem; font-weight: 700; }
.course-card .muted { display: block; }
.selected-badge { margin-left: 8px; }
.catalog-picker { margin: 14px 0; }
</style>
