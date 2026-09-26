<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { challengeApi, classroomApi, getCurrentContext, type ApiError, type ChallengeItem, type UserContext } from '../api'

const context = ref<UserContext | null>(null)
const items = ref<ChallengeItem[]>([])
const selected = ref<ChallengeItem>()
const hints = ref<{ hint_id: string; title: string; content: string; unlock_after_attempts: number }[]>([])
const flag = ref('')
const message = ref('')
const courseId = computed(() => localStorage.getItem('yk-course-id') || 'course_web_security')
const classId = computed(() => localStorage.getItem('yk-class-id') || '')
const releaseId = computed(() => localStorage.getItem('yk-release-id') || '')
const runtimeInstanceId = ref('')
const runtimeStatus = ref('')

function challengeRole(): 'teacher' | 'student' {
  return context.value?.role === 'student' ? 'student' : 'teacher'
}

async function load() {
  context.value = await getCurrentContext()
  const result = await challengeApi.list(courseId.value, challengeRole(), classId.value)
  items.value = result.items
  if (selected.value) selected.value = items.value.find(item => item.challenge_id === selected.value?.challenge_id)
  await loadRuntimeContext()
}

async function loadRuntimeContext() {
  runtimeInstanceId.value = ''
  runtimeStatus.value = ''
  if (challengeRole() !== 'student' || !releaseId.value) return
  try {
    const runtime = await classroomApi<{ runtime_instance_id?: string; status?: string }>(
      `/api/v1/classroom/my/lab-releases/${encodeURIComponent(releaseId.value)}`,
      'student',
    )
    runtimeInstanceId.value = runtime.runtime_instance_id || ''
    runtimeStatus.value = runtime.status || ''
  } catch {
    runtimeStatus.value = 'UNAVAILABLE'
  }
}

async function choose(item: ChallengeItem) {
  selected.value = item
  const result = await challengeApi.hints(item.challenge_id, challengeRole(), classId.value)
  hints.value = result.items
}

async function configureFlag() {
  if (!selected.value || selected.value.validation_mode !== 'FLAG_AND_CHECKPOINT' || !flag.value.trim()) return
  await challengeApi.configureFlag(selected.value.challenge_id, flag.value)
  flag.value = ''
  message.value = 'Flag 已以哈希方式保存，明文不会落库。'
  await load()
}

async function submitChallenge() {
  if (!selected.value || !classId.value) {
    message.value = '请先选择当前班级。'
    return
  }
  const checkpointOnly = selected.value.validation_mode === 'CHECKPOINT_ONLY'
  if (!checkpointOnly && !flag.value.trim()) {
    message.value = '当前挑战需要输入 Flag。'
    return
  }
  await loadRuntimeContext()
  if (!releaseId.value || !runtimeInstanceId.value || runtimeStatus.value !== 'RUNNING') {
    message.value = '请先从“我的实验”启动当前实验，进入运行状态后再提交挑战。'
    return
  }
  try {
    await classroomApi(
      `/api/v1/classroom/my/runtime/${encodeURIComponent(runtimeInstanceId.value)}/rejudge`,
      'student',
      { method: 'POST', body: '{}' },
    )
    await loadRuntimeContext()
    const result = await challengeApi.submit(
      selected.value.challenge_id,
      checkpointOnly ? null : flag.value,
      classId.value,
      releaseId.value,
      runtimeInstanceId.value,
    )
    flag.value = ''
    message.value = result.accepted
      ? '挑战验证通过；完成事实已绑定真实 Checkpoint 证据，成绩继续进入原有成绩链。'
      : `Flag 未通过，还可尝试 ${result.remaining_attempts} 次。`
    await choose(selected.value)
  } catch (error) {
    const detail = error as ApiError
    message.value = detail.code === 'CHALLENGE.CHECKPOINT_REQUIRED'
      ? '当前 Checkpoint 还没有通过。请先完成实验判定，再回来验证挑战。'
      : detail.message || '挑战验证失败，请核对当前实验状态。'
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="hero"><div><h1>挑战训练</h1><p>Hint / Flag / Attempt 只记录挑战过程，正式实验成绩仍由 Checkpoint 统一计算。</p></div></div>
    <p v-if="message" class="status-ok">{{ message }}</p>
    <div class="grid challenge-layout">
      <section class="card">
        <h3>挑战列表</h3>
        <button v-for="item in items" :key="item.challenge_id" type="button" class="challenge-row" :class="{ selected: selected?.challenge_id === item.challenge_id }" @click="choose(item)">
          <span><strong>{{ item.title }}</strong><small>{{ item.difficulty }} · {{ item.status }}</small></span>
          <span class="badge">{{ !item.unlocked ? '未解锁' : item.validation_mode === 'CHECKPOINT_ONLY' ? 'Checkpoint 判定' : item.flag_configured ? 'Flag 已配置' : '待配置 Flag' }}</span>
        </button>
        <p v-if="!items.length" class="muted">当前课程暂无可见挑战。</p>
      </section>
      <section class="card">
        <template v-if="selected">
          <span class="badge">{{ selected.status }}</span><h2>{{ selected.title }}</h2><p>{{ selected.description }}</p>
          <p class="muted">实验定义：{{ selected.lab_definition_id || '待绑定' }} · 冻结版本：{{ selected.lab_version_id || '待绑定' }} · Checkpoint：{{ selected.checkpoint_key || '待真实实验版本完成后绑定' }}</p>
          <p v-if="context?.role === 'student'" class="muted">当前实验：{{ releaseId || '未选择' }} · 运行实例：{{ runtimeInstanceId || '未启动' }} · {{ runtimeStatus || '待读取' }}</p>
          <h3>提示</h3>
          <article v-for="hint in hints" :key="hint.hint_id" class="hint"><strong>{{ hint.title }}</strong><p>{{ hint.content }}</p></article>
          <p class="muted">验证方式：{{ selected.validation_mode === 'CHECKPOINT_ONLY' ? '仅使用权威 Checkpoint，不需要 Flag' : 'Flag + 权威 Checkpoint 双重验证' }}</p>
          <div v-if="selected.validation_mode === 'FLAG_AND_CHECKPOINT'" class="flag-box">
            <input v-model="flag" :placeholder="context?.role === 'student' ? '输入 Flag' : '设置 Flag（明文不会保存）'">
            <button v-if="context?.role === 'teacher'" class="yk-button primary" :disabled="!flag.trim()" @click="configureFlag">安全保存 Flag</button>
            <button v-else class="yk-button primary" :disabled="selected.status !== 'PUBLISHED' || !selected.unlocked || !flag.trim()" @click="submitChallenge">{{ selected.unlocked ? '提交 Flag + Checkpoint 验证' : '请先完成前置挑战' }}</button>
          </div>
          <div v-else-if="context?.role === 'student'" class="flag-box">
            <button class="yk-button primary" :disabled="selected.status !== 'PUBLISHED' || !selected.unlocked" @click="submitChallenge">{{ selected.unlocked ? '验证当前 Checkpoint' : '请先完成前置挑战' }}</button>
          </div>
          <p v-else class="muted">本挑战不配置 Flag；发布后由学生完成绑定实验的 Checkpoint 即可验证。</p>
        </template>
        <p v-else class="muted">从左侧选择一个挑战。</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.challenge-layout { grid-template-columns: minmax(280px, 0.8fr) minmax(0, 1.4fr); gap: 14px; }
.challenge-row { width: 100%; border: 1px solid var(--border); background: var(--surface); padding: 12px; border-radius: 10px; margin: 8px 0; display: flex; justify-content: space-between; text-align: left; color: inherit; }
.challenge-row.selected { border-color: var(--primary); }
.challenge-row small { display: block; margin-top: 4px; opacity: .7; }
.hint { padding: 10px 0; border-bottom: 1px solid var(--border); }
.flag-box { display: flex; gap: 8px; margin-top: 16px; }
.flag-box input { flex: 1; min-width: 0; }
@media (max-width: 900px) { .challenge-layout { grid-template-columns: 1fr; } }
</style>
