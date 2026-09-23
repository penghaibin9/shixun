<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import YkCheck from '../../components/common/YkCheck.vue'
import YkRadio from '../../components/common/YkRadio.vue'
import type { components } from '../api-contract.generated'
import { api, type ApiError } from '../api'

type AnswerValue = string | string[]
type StudentTaskOption = components['schemas']['StudentTaskOptionResponse']
type StudentTaskQuestion = Omit<components['schemas']['StudentTaskQuestionResponse'], 'options'> & {
  options: StudentTaskOption[]
}
type AssignmentSummary = components['schemas']['StudentAssignmentListItemResponse']
type QuizSummary = components['schemas']['StudentQuizListItemResponse']
type AssignmentTask = Omit<components['schemas']['StudentAssignmentTaskResponse'], 'questions'> & {
  questions: StudentTaskQuestion[]
}
type QuizTask = Omit<components['schemas']['StudentQuizTaskResponse'], 'questions'> & {
  questions: StudentTaskQuestion[]
}
type TaskKind = 'assignment' | 'quiz'
type AssignmentLoadedTask = AssignmentTask & { kind: 'assignment'; task_id: string }
type QuizLoadedTask = QuizTask & { kind: 'quiz'; task_id: string }
type LoadedTask = AssignmentLoadedTask | QuizLoadedTask

const message = ref('正在读取本人已发布任务…')
const messageIsError = ref(false)
const loading = ref(false)
const taskError = ref('')
const assignments = ref<AssignmentLoadedTask[]>([])
const quizzes = ref<QuizLoadedTask[]>([])
const answers = ref<Record<string, Record<string, AnswerValue>>>({})
const submittingTask = ref('')
const completedTaskKeys = ref<string[]>([])
const submittingPoll = ref(false)

const questionTypeText: Record<string, string> = {
  FILL: '填空题',
  SINGLE: '单选题',
  MULTIPLE: '多选题',
  TRUE_FALSE: '判断题',
}
const tasks = computed(() => [...assignments.value, ...quizzes.value])
const hasPoll = computed(() => Boolean(localStorage.getItem('yk-poll-id') && localStorage.getItem('yk-poll-option-id')))

function taskKey(task: LoadedTask) {
  return `${task.kind}:${task.task_id}`
}

function taskCompleted(task: LoadedTask) {
  const serverCompleted = task.kind === 'assignment'
    ? task.submission_status === 'SUBMITTED'
    : task.attempt_status === 'SUBMITTED'
  return serverCompleted || completedTaskKeys.value.includes(taskKey(task))
}

function messageFor(value: string, isError = false) {
  message.value = value
  messageIsError.value = isError
}

function answerFor(task: LoadedTask, question: StudentTaskQuestion): AnswerValue | undefined {
  return answers.value[taskKey(task)]?.[question.question_ref_id]
}

function setSingleAnswer(task: LoadedTask, question: StudentTaskQuestion, value: string) {
  const key = taskKey(task)
  answers.value[key] = { ...(answers.value[key] || {}), [question.question_ref_id]: value }
}

function multipleSelected(task: LoadedTask, question: StudentTaskQuestion, optionKey: string) {
  const answer = answerFor(task, question)
  return Array.isArray(answer) && answer.includes(optionKey)
}

function updateMultipleAnswer(task: LoadedTask, question: StudentTaskQuestion, optionKey: string, checked: boolean) {
  const previous = answerFor(task, question)
  const values = Array.isArray(previous) ? previous : []
  const next = checked ? [...new Set([...values, optionKey])] : values.filter(item => item !== optionKey)
  const key = taskKey(task)
  answers.value[key] = { ...(answers.value[key] || {}), [question.question_ref_id]: next }
}

function singleAnswer(task: LoadedTask, question: StudentTaskQuestion) {
  const answer = answerFor(task, question)
  return typeof answer === 'string' ? answer : ''
}

function hasAnswer(task: LoadedTask, question: StudentTaskQuestion) {
  const answer = answerFor(task, question)
  return Array.isArray(answer) ? answer.length > 0 : typeof answer === 'string' && answer.trim().length > 0
}

function canRenderQuestion(question: StudentTaskQuestion) {
  return question.question_type === 'FILL' || question.options.length > 0
}

function allAnswered(task: LoadedTask) {
  return task.questions.length > 0 && task.questions.every(question => canRenderQuestion(question) && hasAnswer(task, question))
}

function requestAnswers(task: LoadedTask) {
  if (!allAnswered(task)) throw new Error('请完成当前任务中的每一道题目后再提交。')
  const result: Record<string, AnswerValue> = {}
  for (const question of task.questions) {
    const answer = answerFor(task, question)
    if (answer === undefined) throw new Error('作答内容不完整。')
    // The key is the server-issued frozen-question reference.  The browser
    // deliberately carries answers only, never a score, snapshot or version.
    result[question.question_ref_id] = answer
  }
  return result
}

function isPublished(status: string) {
  return status === 'PUBLISHED'
}

function normalizeQuestion(question: components['schemas']['StudentTaskQuestionResponse']): StudentTaskQuestion {
  return { ...question, options: question.options ?? [] }
}

function normalizeAssignmentTask(task: components['schemas']['StudentAssignmentTaskResponse']): AssignmentTask {
  return { ...task, questions: task.questions.map(normalizeQuestion) }
}

function normalizeQuizTask(task: components['schemas']['StudentQuizTaskResponse']): QuizTask {
  return { ...task, questions: task.questions.map(normalizeQuestion) }
}

async function loadTasks() {
  loading.value = true
    taskError.value = ''
    try {
      const [assignmentList, quizList] = await Promise.all([
      api<components['schemas']['StudentAssignmentListResponse']>('/api/v1/assignments/my', {}, 'student'),
      api<components['schemas']['StudentQuizListResponse']>('/api/v1/quizzes/my', {}, 'student'),
    ])
    const publishedAssignments = assignmentList.items.filter(item => isPublished(item.status))
    const publishedQuizzes = quizList.items.filter(item => isPublished(item.status))
    const [assignmentDetails, quizDetails] = await Promise.all([
      Promise.all(publishedAssignments.map(async item => {
        const task = normalizeAssignmentTask(await api<components['schemas']['StudentAssignmentTaskResponse']>(`/api/v1/assignments/${encodeURIComponent(item.assignment_id)}/student-task`, {}, 'student'))
        return { ...task, kind: 'assignment' as const, task_id: item.assignment_id } satisfies AssignmentLoadedTask
      })),
      Promise.all(publishedQuizzes.map(async item => {
        const task = normalizeQuizTask(await api<components['schemas']['StudentQuizTaskResponse']>(`/api/v1/quizzes/${encodeURIComponent(item.quiz_id)}/student-task`, {}, 'student'))
        return { ...task, kind: 'quiz' as const, task_id: item.quiz_id } satisfies QuizLoadedTask
      })),
    ])
    assignments.value = assignmentDetails
    quizzes.value = quizDetails
    answers.value = {}
    messageFor(tasks.value.length ? '已读取本人已发布任务，请按服务端下发的冻结题目作答。' : '当前没有可作答的已发布任务。')
  } catch (error) {
    assignments.value = []
    quizzes.value = []
    taskError.value = (error as ApiError).message || (error as Error).message || '已发布任务读取失败。'
    messageFor(taskError.value, true)
  } finally {
    loading.value = false
  }
}

async function submitPoll() {
  const pollId = localStorage.getItem('yk-poll-id')
  const optionId = localStorage.getItem('yk-poll-option-id')
  if (!pollId || !optionId) return
  submittingPoll.value = true
  try {
    await api(`/api/v1/polls/${encodeURIComponent(pollId)}/answers`, { method: 'POST', body: JSON.stringify({ option_id: optionId }) }, 'student')
    messageFor('课堂投票已提交。')
  } catch (error) {
    messageFor((error as ApiError).message, true)
  } finally {
    submittingPoll.value = false
  }
}

async function submitAssignment(task: LoadedTask) {
  const key = taskKey(task)
  submittingTask.value = key
  try {
    const answersPayload = requestAnswers(task)
    await api(`/api/v1/assignments/${encodeURIComponent(task.task_id)}/submit`, { method: 'POST', body: JSON.stringify({ answers: answersPayload }) }, 'student')
    completedTaskKeys.value = [...new Set([...completedTaskKeys.value, key])]
    messageFor('作业已提交，分数由服务端按冻结题目自动判定。')
  } catch (error) {
    messageFor((error as ApiError).message || (error as Error).message, true)
  } finally {
    submittingTask.value = ''
  }
}

async function submitQuiz(task: LoadedTask) {
  const key = taskKey(task)
  submittingTask.value = key
  try {
    const answersPayload = requestAnswers(task)
    const attempt = await api<{ attempt_id: string }>(`/api/v1/quizzes/${encodeURIComponent(task.task_id)}/attempts`, { method: 'POST' }, 'student')
    await api(`/api/v1/quizzes/${encodeURIComponent(task.task_id)}/attempts/${encodeURIComponent(attempt.attempt_id)}/submit`, { method: 'POST', body: JSON.stringify({ answers: answersPayload }) }, 'student')
    completedTaskKeys.value = [...new Set([...completedTaskKeys.value, key])]
    messageFor('课堂小测已提交，分数由服务端按冻结题目自动判定。')
  } catch (error) {
    messageFor((error as ApiError).message || (error as Error).message, true)
  } finally {
    submittingTask.value = ''
  }
}

onMounted(() => { void loadTasks() })
</script>

<template>
  <div>
    <div class="hero">
      <div>
        <h1>作业与测验</h1>
        <p>只展示服务端允许本人作答的已发布任务；提交后由服务端按冻结题目自动判分。</p>
      </div>
      <button class="yk-button" :disabled="loading" @click="loadTasks">刷新任务</button>
    </div>
    <p data-testid="student-work-message" :class="messageIsError ? 'status-error' : 'status-ok'">{{ message }}</p>

    <section v-if="hasPoll" class="card" style="margin-bottom:14px">
      <div class="row-between"><div><h3>当前课堂投票</h3><p class="muted">投票答案由当前课堂已发布投票确定。</p></div><button class="yk-button" :disabled="submittingPoll" @click="submitPoll">{{ submittingPoll ? '正在提交…' : '提交当前课堂投票' }}</button></div>
    </section>

    <p v-if="loading" class="muted">正在读取服务端任务…</p>
    <p v-else-if="taskError" data-testid="student-task-error" class="status-error">{{ taskError }}</p>
    <section v-else-if="!tasks.length" data-testid="student-task-empty" class="card muted">当前没有可作答的已发布任务。</section>

    <div v-else class="task-list">
      <section v-for="task in assignments" :key="taskKey(task)" :data-testid="`assignment-task-${task.task_id}`" class="card task-card">
        <div class="row-between"><div><h3>{{ task.title }}</h3><p class="muted">课后作业 · {{ task.questions.length }} 题</p></div><span class="badge">{{ taskCompleted(task) ? '已提交' : '已发布' }}</span></div>
        <div v-for="question in task.questions" :key="question.question_ref_id" :data-testid="`student-question-assignment-${task.task_id}-${question.question_ref_id}`" class="question-card">
          <b>{{ questionTypeText[question.question_type] || '练习题' }}</b>
          <p>{{ question.stem }}</p>
          <div v-if="question.question_type === 'FILL'" class="yk-field"><label :for="`answer-${task.task_id}-${question.question_ref_id}`">你的作答</label><input :id="`answer-${task.task_id}-${question.question_ref_id}`" class="yk-input" :value="singleAnswer(task, question)" @input="setSingleAnswer(task, question, ($event.target as HTMLInputElement).value)"></div>
          <div v-else-if="question.question_type === 'MULTIPLE'" role="group" :aria-label="question.stem" class="answer-options"><YkCheck v-for="option in question.options" :key="option.key" :model-value="multipleSelected(task, question, option.key)" :label="`${option.key}. ${option.text}`" @update:model-value="updateMultipleAnswer(task, question, option.key, $event)" /></div>
          <div v-else-if="question.options.length" role="radiogroup" :aria-label="question.stem" class="answer-options"><YkRadio v-for="option in question.options" :key="option.key" :model-value="singleAnswer(task, question)" :value="option.key" :label="`${option.key}. ${option.text}`" @update:model-value="setSingleAnswer(task, question, $event)" /></div>
          <p v-else class="status-error">题目缺少可作答选项，暂不能提交。</p>
        </div>
        <button class="yk-button primary" :disabled="submittingTask === taskKey(task) || !allAnswered(task) || taskCompleted(task)" @click="submitAssignment(task)">{{ taskCompleted(task) ? '已提交' : submittingTask === taskKey(task) ? '正在提交…' : '提交作业' }}</button>
      </section>

      <section v-for="task in quizzes" :key="taskKey(task)" :data-testid="`quiz-task-${task.task_id}`" class="card task-card">
        <div class="row-between"><div><h3>{{ task.title }}</h3><p class="muted">课堂小测 · {{ task.questions.length }} 题<span v-if="task.time_limit_minutes"> · {{ task.time_limit_minutes }} 分钟</span></p></div><span class="badge">{{ taskCompleted(task) ? '已提交' : '已发布' }}</span></div>
        <div v-for="question in task.questions" :key="question.question_ref_id" :data-testid="`student-question-quiz-${task.task_id}-${question.question_ref_id}`" class="question-card">
          <b>{{ questionTypeText[question.question_type] || '练习题' }}</b>
          <p>{{ question.stem }}</p>
          <div v-if="question.question_type === 'FILL'" class="yk-field"><label :for="`answer-${task.task_id}-${question.question_ref_id}`">你的作答</label><input :id="`answer-${task.task_id}-${question.question_ref_id}`" class="yk-input" :value="singleAnswer(task, question)" @input="setSingleAnswer(task, question, ($event.target as HTMLInputElement).value)"></div>
          <div v-else-if="question.question_type === 'MULTIPLE'" role="group" :aria-label="question.stem" class="answer-options"><YkCheck v-for="option in question.options" :key="option.key" :model-value="multipleSelected(task, question, option.key)" :label="`${option.key}. ${option.text}`" @update:model-value="updateMultipleAnswer(task, question, option.key, $event)" /></div>
          <div v-else-if="question.options.length" role="radiogroup" :aria-label="question.stem" class="answer-options"><YkRadio v-for="option in question.options" :key="option.key" :model-value="singleAnswer(task, question)" :value="option.key" :label="`${option.key}. ${option.text}`" @update:model-value="setSingleAnswer(task, question, $event)" /></div>
          <p v-else class="status-error">题目缺少可作答选项，暂不能提交。</p>
        </div>
        <button class="yk-button primary" :disabled="submittingTask === taskKey(task) || !allAnswered(task) || taskCompleted(task)" @click="submitQuiz(task)">{{ taskCompleted(task) ? '已提交' : submittingTask === taskKey(task) ? '正在提交…' : '开始并提交测验' }}</button>
      </section>
    </div>
  </div>
</template>

<style scoped>
.task-list { display: grid; gap: 14px; }
.task-card { display: grid; gap: 14px; }
.question-card { border-top: 1px solid var(--line); padding-top: 14px; }
.question-card p { margin: 8px 0; }
.answer-options { display: grid; gap: 8px; }
</style>
