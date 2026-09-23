<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import YkCheck from '../../components/common/YkCheck.vue'
import YkSelect from '../../components/common/YkSelect.vue'
import type { components } from '../api-contract.generated'
import { api, resourceApi, type ApiError } from '../api'

type QuestionOption = Pick<components['schemas']['QuestionOptionResponse'], 'key' | 'text'>
type PublishedQuestion = Pick<components['schemas']['QuestionResponse'], 'question_id' | 'question_type' | 'stem' | 'status' | 'lesson_id'> & {
  options: QuestionOption[]
}
type PublishedTask = { assignment_id?: string; quiz_id?: string; title?: string; status?: string }

const pollType = ref('UNDERSTANDING')
const message = ref('')
const messageIsError = ref(false)
const results = ref<{ label: string; count: number }[]>([])
const questions = ref<PublishedQuestion[]>([])
const selectedQuestionIds = ref<string[]>([])
const loadingQuestions = ref(false)
const questionError = ref('')
const publishingWork = ref(false)
const publishedTasks = ref<{ assignment: PublishedTask; quiz: PublishedTask }>()

const modes = [
  { value: 'UNDERSTANDING', label: '理解度投票' },
  { value: 'ASSIGNMENT_COMPLETION', label: '作业完成情况' },
  { value: 'TEACHING_FEEDBACK', label: '教学反馈' },
]
const questionTypeText: Record<string, string> = {
  FILL: '填空题',
  SINGLE: '单选题',
  MULTIPLE: '多选题',
  TRUE_FALSE: '判断题',
}
const publishedQuestions = computed(() => questions.value.filter(item => item.status === 'PUBLISHED'))
const selectedQuestions = computed(() => publishedQuestions.value.filter(item => selectedQuestionIds.value.includes(item.question_id)))

function setMessage(value: string, isError = false) {
  message.value = value
  messageIsError.value = isError
}

function selected(questionId: string) {
  return selectedQuestionIds.value.includes(questionId)
}

function updateQuestionSelection(questionId: string, checked: boolean) {
  if (checked && !selected(questionId)) selectedQuestionIds.value = [...selectedQuestionIds.value, questionId]
  if (!checked) selectedQuestionIds.value = selectedQuestionIds.value.filter(item => item !== questionId)
}

async function loadPublishedQuestions() {
  const courseId = localStorage.getItem('yk-course-id')?.trim()
  questions.value = []
  selectedQuestionIds.value = []
  questionError.value = ''
  if (!courseId) {
    questionError.value = '请先在课程中心选择当前课程，再加载可发布题目。'
    return
  }
  loadingQuestions.value = true
  try {
    const response = await resourceApi.publishedQuestions()
    questions.value = response.items
      .filter(item => item.status === 'PUBLISHED')
      .map<PublishedQuestion>(({ question_id, question_type, stem, status, lesson_id, options }) => ({
        question_id,
        question_type,
        stem,
        status,
        lesson_id,
        options: (options ?? []).map(({ key, text }) => ({ key, text })),
      }))
    if (!questions.value.length) questionError.value = '当前课程没有已发布且经独立审核的题目，不能创建作业或测验。'
  } catch (error) {
    questionError.value = (error as ApiError).message || '已发布题目读取失败。'
  } finally {
    loadingQuestions.value = false
  }
}

async function publishPoll() {
  try {
    const courseId = localStorage.getItem('yk-course-id')
    const classId = localStorage.getItem('yk-class-id')
    if (!courseId || !classId) {
      setMessage('请先选择课程和班级，再发布投票。', true)
      return
    }
    const labels = pollType.value === 'UNDERSTANDING'
      ? ['完全掌握', '基本掌握', '需要复习']
      : pollType.value === 'ASSIGNMENT_COMPLETION'
        ? ['已完成', '进行中', '未开始']
        : ['很好', '一般', '需改进']
    const poll = await api<{ poll_id: string; options: { option_id: string }[] }>('/api/v1/polls', {
      method: 'POST',
      body: JSON.stringify({ course_id: courseId, class_id: classId, poll_type: pollType.value, title: '课堂反馈', options: labels }),
    }, 'teacher')
    await api(`/api/v1/polls/${encodeURIComponent(poll.poll_id)}/publish`, { method: 'POST' }, 'teacher')
    localStorage.setItem('yk-poll-id', poll.poll_id)
    localStorage.setItem('yk-poll-option-id', poll.options[0].option_id)
    setMessage('投票已发布')
  } catch (error) {
    setMessage((error as ApiError).message, true)
  }
}

async function publishWork() {
  const courseId = localStorage.getItem('yk-course-id')?.trim()
  const classId = localStorage.getItem('yk-class-id')?.trim()
  const questionIds = selectedQuestions.value.map(item => item.question_id)
  if (!courseId || !classId) {
    setMessage('请先选择课程和班级，再发布作业或测验。', true)
    return
  }
  if (!questionIds.length) {
    setMessage('请至少选择一道当前课程已发布题目。', true)
    return
  }
  publishingWork.value = true
  try {
    const questionRefs = questionIds.map(question_id => ({ question_id }))
    const assignment = await api<PublishedTask>('/api/v1/assignments', {
      method: 'POST',
      body: JSON.stringify({
        course_id: courseId,
        class_id: classId,
        title: `课后作业（${questionRefs.length} 题）`,
        due_at: new Date(Date.now() + 86400000).toISOString().replace('Z', ''),
        random_order: true,
        questions: questionRefs,
      }),
    }, 'teacher')
    if (!assignment.assignment_id) throw new Error('服务端没有返回作业标识。')
    await api(`/api/v1/assignments/${encodeURIComponent(assignment.assignment_id)}/publish`, { method: 'POST' }, 'teacher')

    const quiz = await api<PublishedTask>('/api/v1/quizzes', {
      method: 'POST',
      body: JSON.stringify({
        course_id: courseId,
        class_id: classId,
        title: `课堂小测（${questionRefs.length} 题）`,
        time_limit_minutes: 10,
        random_order: true,
        questions: questionRefs,
      }),
    }, 'teacher')
    if (!quiz.quiz_id) throw new Error('服务端没有返回测验标识。')
    await api(`/api/v1/quizzes/${encodeURIComponent(quiz.quiz_id)}/publish`, { method: 'POST' }, 'teacher')
    publishedTasks.value = { assignment, quiz }
    setMessage('作业与测验已发布')
  } catch (error) {
    setMessage((error as ApiError).message || (error as Error).message, true)
  } finally {
    publishingWork.value = false
  }
}

async function loadResults() {
  const pollId = localStorage.getItem('yk-poll-id')
  if (!pollId) {
    setMessage('尚未发布可查看的投票。', true)
    return
  }
  try {
    results.value = (await api<{ items: { label: string; count: number }[] }>(`/api/v1/polls/${encodeURIComponent(pollId)}/results`, {}, 'teacher')).items
  } catch (error) {
    setMessage((error as ApiError).message, true)
  }
}

onMounted(() => { void loadPublishedQuestions() })
</script>

<template>
  <div>
    <div class="hero">
      <div>
        <h1>作业与测验</h1>
        <p>教师只选择当前课程已发布题目；题目快照、分值与判分规则均由服务端冻结。</p>
      </div>
      <button class="yk-button primary" :disabled="publishingWork || loadingQuestions || !selectedQuestionIds.length" @click="publishWork">
        {{ publishingWork ? '正在发布…' : '＋ 发布课后作业与小测' }}
      </button>
    </div>
    <p v-if="message" data-testid="work-message" :class="messageIsError ? 'status-error' : 'status-ok'">{{ message }}</p>

    <div class="grid grid-2">
      <section class="card">
        <div class="section-head"><h3>在线投票</h3><span class="badge">三种模式</span></div>
        <label class="yk-field"><span>投票方式</span><YkSelect v-model="pollType" :options="modes" /></label>
        <div class="actions" style="margin-top:12px">
          <button class="yk-button primary" @click="publishPoll">发布投票</button>
          <button class="yk-button" @click="loadResults">查看统计</button>
        </div>
        <div v-for="row in results" :key="row.label" class="poll-result"><span>{{ row.label }}</span><b>{{ row.count }} 人</b></div>
      </section>

      <section class="card" aria-labelledby="published-question-heading">
        <div class="section-head">
          <div>
            <h3 id="published-question-heading">已发布题目</h3>
            <p class="muted">仅展示当前课程中可由服务端冻结的独立审核题目。</p>
          </div>
          <button class="yk-button" :disabled="loadingQuestions" @click="loadPublishedQuestions">刷新题目</button>
        </div>
        <p v-if="loadingQuestions" class="muted">正在读取题目…</p>
        <p v-else-if="questionError" data-testid="question-load-state" class="status-error">{{ questionError }}</p>
        <div v-else-if="publishedQuestions.length" class="question-list" data-testid="published-question-list">
          <article v-for="question in publishedQuestions" :key="question.question_id" :data-testid="`published-question-${question.question_id}`" class="card question-choice">
            <YkCheck :model-value="selected(question.question_id)" :label="`选择：${question.stem}`" @update:model-value="updateQuestionSelection(question.question_id, $event)" />
            <div class="question-copy">
              <span class="badge">{{ questionTypeText[question.question_type] || '其他题型' }}</span>
              <p>{{ question.stem }}</p>
              <ol v-if="question.options.length" class="muted">
                <li v-for="option in question.options" :key="option.key">{{ option.key }}. {{ option.text }}</li>
              </ol>
            </div>
          </article>
        </div>
        <p v-else class="muted">当前课程暂无可选择题目。</p>
        <p v-if="selectedQuestionIds.length" class="muted">已选择 {{ selectedQuestionIds.length }} 道题目；浏览器只会提交题目选择，不会提交题目快照、版本或分值。</p>
      </section>
    </div>

    <section v-if="publishedTasks" class="card" data-testid="published-task-summary" style="margin-top:14px">
      <h3>本次已发布任务</h3>
      <p class="muted">作业：{{ publishedTasks.assignment.title || '已发布' }}；测验：{{ publishedTasks.quiz.title || '已发布' }}。学生端会重新从服务端读取本人可作答任务。</p>
    </section>
  </div>
</template>

<style scoped>
.question-list { display: grid; gap: 10px; max-height: 460px; overflow: auto; }
.question-choice { padding: 12px; }
.question-copy { margin-top: 8px; }
.question-copy p { margin: 8px 0; }
.question-copy ol { margin: 0; padding-left: 22px; }
</style>
