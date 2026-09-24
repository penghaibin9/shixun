<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { challengeApi, getCurrentContext, type ChallengeItem, type UserContext } from '../api'

const context = ref<UserContext | null>(null)
const items = ref<ChallengeItem[]>([])
const selected = ref<ChallengeItem>()
const hints = ref<{ hint_id: string; title: string; content: string; unlock_after_attempts: number }[]>([])
const flag = ref('')
const message = ref('')
const courseId = computed(() => localStorage.getItem('yk-course-id') || 'course_web_security')
const classId = computed(() => localStorage.getItem('yk-class-id') || '')

function challengeRole(): 'teacher' | 'student' {
  return context.value?.role === 'student' ? 'student' : 'teacher'
}

async function load() {
  context.value = await getCurrentContext()
  const result = await challengeApi.list(courseId.value, challengeRole())
  items.value = result.items
  if (selected.value) selected.value = items.value.find(item => item.challenge_id === selected.value?.challenge_id)
}

async function choose(item: ChallengeItem) {
  selected.value = item
  const result = await challengeApi.hints(item.challenge_id, challengeRole())
  hints.value = result.items
}

async function configureFlag() {
  if (!selected.value || !flag.value.trim()) return
  await challengeApi.configureFlag(selected.value.challenge_id, flag.value)
  flag.value = ''
  message.value = 'Flag 已以哈希方式保存，明文不会落库。'
  await load()
}

async function submitFlag() {
  if (!selected.value || !flag.value.trim() || !classId.value) {
    message.value = '请先选择班级并输入 Flag。'
    return
  }
  const result = await challengeApi.submit(selected.value.challenge_id, flag.value, classId.value)
  flag.value = ''
  message.value = result.accepted ? '挑战验证通过；完成事实已记录，课程成绩仍以 Checkpoint 为准。' : `未通过，还可尝试 ${result.remaining_attempts} 次。`
  await choose(selected.value)
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
          <span class="badge">{{ item.flag_configured ? 'Flag 已配置' : '待配置' }}</span>
        </button>
        <p v-if="!items.length" class="muted">当前课程暂无可见挑战。</p>
      </section>
      <section class="card">
        <template v-if="selected">
          <span class="badge">{{ selected.status }}</span><h2>{{ selected.title }}</h2><p>{{ selected.description }}</p>
          <p class="muted">实验定义：{{ selected.lab_definition_id || '待绑定' }} · Checkpoint：{{ selected.checkpoint_key || '待真实实验版本完成后绑定' }}</p>
          <h3>提示</h3>
          <article v-for="hint in hints" :key="hint.hint_id" class="hint"><strong>{{ hint.title }}</strong><p>{{ hint.content }}</p></article>
          <div class="flag-box">
            <input v-model="flag" :placeholder="context?.role === 'student' ? '输入 Flag' : '设置 Flag（明文不会保存）'">
            <button v-if="context?.role === 'teacher'" class="yk-button primary" :disabled="!flag.trim()" @click="configureFlag">安全保存 Flag</button>
            <button v-else class="yk-button primary" :disabled="selected.status !== 'PUBLISHED' || !flag.trim()" @click="submitFlag">提交验证</button>
          </div>
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
