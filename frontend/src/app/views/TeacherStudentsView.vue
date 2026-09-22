<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import YkDrawer from '../../components/common/YkDrawer.vue'
import YkSelect from '../../components/common/YkSelect.vue'
import { api, download, fileIdempotencyKey, type ApiError } from '../api'

type Member = { class_membership_id: string; student_id: string; student_number: string; student_name: string; phone: string | null; email: string | null; status: string }
type Summary = { attendance: { signed: number; total: number }; assignment_submitted: number; quiz_completed: number; experiment: { label: string }; grade: { label: string }; risk: { label: string } }
type ImportResult = { job_id: string; success_count: number; failure_count: number; duplicate_count: number }

const classId = ref(localStorage.getItem('yk-class-id') || '')
const courseId = ref(localStorage.getItem('yk-course-id') || '')
const courseOptions = ref<{ value: string; label: string }[]>([])
const classOptions = ref<{ value: string; label: string }[]>([])
const search = ref('')
const status = ref('ACTIVE')
const sort = ref('student_number')
const direction = ref('asc')
const page = ref(1)
const total = ref(0)
const items = ref<Member[]>([])
const loading = ref(false)
const denied = ref(false)
const message = ref('')
const selected = ref<Member>()
const summary = ref<Summary>()
const file = ref<File>()
const importResult = ref<ImportResult>()
const pageSize = 10
const statusOptions = [{ value: 'ACTIVE', label: '在读账号' }, { value: 'REMOVED', label: '已移出' }]
const sortOptions = [{ value: 'student_number', label: '按学号排序' }, { value: 'student_name', label: '按姓名排序' }]
const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

async function load() {
  if (!classId.value) return
  loading.value = true
  denied.value = false
  try {
    const query = new URLSearchParams({ search: search.value, status: status.value, sort: sort.value, direction: direction.value, page: String(page.value), page_size: String(pageSize) })
    const data = await api<{ items: Member[]; total: number }>(`/api/v1/classes/${classId.value}/members?${query}`)
    items.value = data.items
    total.value = data.total
  } catch (error) {
    denied.value = (error as ApiError).code?.startsWith('AUTH.')
    message.value = (error as ApiError).message
  } finally {
    loading.value = false
  }
}

async function loadFilters() {
  const courses = await api<{ items: { course_id: string; name: string }[] }>('/api/v1/courses')
  const classes = await api<{ items: { class_id: string; name: string }[] }>('/api/v1/classes')
  courseOptions.value = courses.items.map(item => ({ value: item.course_id, label: item.name }))
  classOptions.value = classes.items.map(item => ({ value: item.class_id, label: item.name }))
}

async function openDetail(item: Member) {
  selected.value = await api(`/api/v1/classes/${classId.value}/members/${item.class_membership_id}`)
  summary.value = await api(`/api/v1/classes/${classId.value}/members/${item.class_membership_id}/learning-summary`)
}

async function addExisting() {
  const number = prompt('请输入已有学生的学号')
  const name = number && prompt('请输入学生姓名')
  if (!number || !name) return
  await api(`/api/v1/classes/${classId.value}/members`, { method: 'POST', body: JSON.stringify({ student_number: number, student_name: name }) })
  message.value = '学生已加入班级'
  await load()
}

async function remove(item: Member) {
  if (!confirm(`确认将 ${item.student_name} 移出班级？历史教学事实会保留。`)) return
  await api(`/api/v1/classes/${classId.value}/members/${item.class_membership_id}`, { method: 'DELETE' })
  selected.value = undefined
  message.value = '已移出班级'
  await load()
}

async function importList() {
  if (!file.value) return
  const form = new FormData()
  form.append('file', file.value)
  const idempotencyKey = await fileIdempotencyKey('members', file.value)
  importResult.value = await api<ImportResult>(`/api/v1/classes/${classId.value}/members/import`, { method: 'POST', body: form, headers: { 'Idempotency-Key': idempotencyKey } })
  message.value = `导入成功 ${importResult.value.success_count} 人，失败 ${importResult.value.failure_count} 人`
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

async function downloadImportErrors() {
  if (importResult.value?.job_id) await saveBlob(`/api/v1/import-jobs/${importResult.value.job_id}/error-rows.xlsx`, 'student-import-errors.xlsx')
}

watch([status, sort, direction, classId], () => { page.value = 1; localStorage.setItem('yk-class-id', classId.value); load() })
onMounted(async () => { try { await loadFilters() } catch {} await load() })
</script>

<template>
  <div>
    <div class="hero"><div><h1>学生管理</h1><p>按本人任课课程和班级管理学生归班关系，不复制成绩、实验或风险事实。</p></div><div class="actions"><button class="yk-button" @click="saveBlob(`/api/v1/classes/${classId}/members/import-template`,'student-import-template.xlsx')">下载模板</button><button class="yk-button" @click="saveBlob(`/api/v1/classes/${classId}/members/export.xlsx`,'class-members.xlsx')">导出名单</button><button class="yk-button primary" @click="addExisting">＋ 新增已有学生</button></div></div>
    <div class="grid grid-4"><div class="card kpi"><span>当前学生</span><b>{{ total }}</b></div><div class="card kpi"><span>签到数据</span><b>可追溯</b></div><div class="card kpi"><span>作业 / 测验</span><b>可追溯</b></div><div class="card kpi"><span>实验 / 总评 / 风险</span><b style="font-size:16px">数据待汇总</b></div></div>
    <section class="card" style="margin-top:14px">
      <div class="form-grid"><YkSelect v-model="courseId" label="课程" :options="courseOptions"/><YkSelect v-model="classId" label="本人班级" :options="classOptions"/><label class="yk-field"><span>姓名 / 学号搜索</span><input v-model="search" class="input" placeholder="输入姓名或学号" @keyup.enter="page=1;load()"></label><YkSelect v-model="status" label="账号状态" :options="statusOptions"/><YkSelect v-model="sort" label="排序字段" :options="sortOptions"/><YkSelect v-model="direction" label="排序方向" :options="[{value:'asc',label:'升序'},{value:'desc',label:'降序'}]"/></div>
      <div class="actions" style="margin-top:12px"><button class="yk-button" @click="load">查询</button><input aria-label="导入学生名单" type="file" accept=".xlsx" @change="file=($event.target as HTMLInputElement).files?.[0]"><button class="yk-button primary" :disabled="!file" @click="importList">导入学生</button><button v-if="importResult?.failure_count" class="yk-button" data-testid="student-import-error-download" @click="downloadImportErrors">下载逐行错误文件</button><RouterLink class="yk-button" to="/attendance-management">进入签到</RouterLink><RouterLink class="yk-button" to="/teacher-assignments">进入作业与测验</RouterLink></div>
      <p v-if="message" class="status-ok">{{ message }}</p>
      <div v-if="loading" class="empty">正在加载学生名单…</div><div v-else-if="denied" class="empty status-error">无权限查看该班级</div><div v-else-if="!items.length" class="empty">没有符合条件的学生</div>
      <table v-else class="data-table"><thead><tr><th>学号</th><th>姓名</th><th>账号状态</th><th>操作</th></tr></thead><tbody><tr v-for="item in items" :key="item.class_membership_id"><td>{{ item.student_number }}</td><td>{{ item.student_name }}</td><td><span class="badge">{{ item.status==='ACTIVE'?'在读':'已移出' }}</span></td><td><button class="yk-button" @click="openDetail(item)">查看详情</button><button v-if="item.status==='ACTIVE'" class="yk-button danger" @click="remove(item)">移出班级</button></td></tr></tbody></table>
      <div class="row-between"><span>第 {{ page }} / {{ pages }} 页，共 {{ total }} 人</span><div class="actions"><button class="yk-button" :disabled="page<=1" @click="page--;load()">上一页</button><button class="yk-button" :disabled="page>=pages" @click="page++;load()">下一页</button></div></div>
    </section>
    <YkDrawer :open="!!selected" title="学生详情" @close="selected=undefined"><div v-if="selected" class="drawer-detail"><b>{{ selected.student_name }} · {{ selected.student_number }}</b><span>邮箱：{{ selected.email||'未填写' }}</span><span>手机：{{ selected.phone||'未填写' }}</span><hr><b>学习汇总</b><span>签到：{{ summary?.attendance.signed||0 }} / {{ summary?.attendance.total||0 }}</span><span>已交作业：{{ summary?.assignment_submitted||0 }}</span><span>已完成测验：{{ summary?.quiz_completed||0 }}</span><span>实验：{{ summary?.experiment.label }}</span><span>课程总评：{{ summary?.grade.label }}</span><span>风险：{{ summary?.risk.label }}</span></div></YkDrawer>
  </div>
</template>
