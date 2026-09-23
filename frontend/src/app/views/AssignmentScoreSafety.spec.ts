import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import StudentQuizView from './StudentQuizView.vue'
import TeacherAssignmentsView from './TeacherAssignmentsView.vue'

const publishedQuestion = {
  question_id: 'question-live-1',
  lesson_id: 'lesson-live-1',
  question_type: 'SINGLE',
  stem: '动态题目：当前课程中公开给通信对方的是哪一类密钥？',
  status: 'PUBLISHED',
  options: [
    { key: 'A', text: '公钥' },
    { key: 'B', text: '私钥' },
  ],
  created_by: 'resource-author',
  created_at: '2026-09-22T10:00:00',
}

describe('作业与测验服务端评分请求', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('yk-course-id', 'course-a')
    localStorage.setItem('yk-class-id', 'class-a')
    localStorage.setItem('yk-student-id', 'student-a')
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('教师从真实已发布题目列表选择题目，不把快照、版本或分值交给浏览器', async () => {
    const teacherQuestion = {
      ...publishedQuestion,
      answer: ['A'],
      explanation: '敏感解析，不应展示在教师选题页面。',
      options: [
        { key: 'A', text: '公钥', is_correct: true },
        { key: 'B', text: '私钥', is_correct: false },
      ],
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/v1/questions?status=PUBLISHED&course_id=course-a') return { ok: true, json: async () => ({ items: [teacherQuestion] }) }
      if (path === '/api/v1/assignments') return { ok: true, json: async () => ({ assignment_id: 'assignment-a', title: '课后作业（1 题）' }) }
      if (path === '/api/v1/assignments/assignment-a/publish') return { ok: true, json: async () => ({ status: 'PUBLISHED' }) }
      if (path === '/api/v1/quizzes') return { ok: true, json: async () => ({ quiz_id: 'quiz-a', title: '课堂小测（1 题）' }) }
      if (path === '/api/v1/quizzes/quiz-a/publish') return { ok: true, json: async () => ({ status: 'PUBLISHED' }) }
      throw new Error(`未模拟请求：${path} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(TeacherAssignmentsView)
    await flushPromises()

    expect(wrapper.text()).not.toContain('敏感解析，不应展示在教师选题页面。')
    const question = wrapper.get('[data-testid="published-question-question-live-1"]')
    await question.get('button[role="checkbox"]').trigger('click')
    await wrapper.get('button.yk-button.primary').trigger('click')
    await flushPromises()

    expect(fetchMock.mock.calls.some(([path]) => String(path) === '/api/v1/questions?status=PUBLISHED&course_id=course-a')).toBe(true)
    const assignmentCall = fetchMock.mock.calls.find(([path]) => String(path) === '/api/v1/assignments')
    const quizCall = fetchMock.mock.calls.find(([path]) => String(path) === '/api/v1/quizzes')
    for (const call of [assignmentCall, quizCall]) {
      const payload = JSON.parse(String(call?.[1]?.body))
      expect(payload.questions).toEqual([{ question_id: 'question-live-1' }])
      expect(payload).not.toHaveProperty('raw_score')
      expect(payload).not.toHaveProperty('max_score')
      expect(payload.questions[0]).not.toHaveProperty('question_snapshot')
      expect(payload.questions[0]).not.toHaveProperty('question_version')
      expect(payload.questions[0]).not.toHaveProperty('source_proof')
    }
  })

  it('学生任务缺少选项时归一化为空数组，并阻止不可作答题目提交', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/v1/assignments/my') return { ok: true, json: async () => ({ items: [{ assignment_id: 'assignment-empty-options', title: '空选项作业', status: 'PUBLISHED' }] }) }
      if (path === '/api/v1/quizzes/my') return { ok: true, json: async () => ({ items: [] }) }
      if (path === '/api/v1/assignments/assignment-empty-options/student-task') return {
        ok: true,
        json: async () => ({
          assignment_id: 'assignment-empty-options',
          title: '空选项作业',
          status: 'PUBLISHED',
          questions: [{ question_ref_id: 'empty-options-ref', question_id: 'question-empty-options', question_type: 'SINGLE', stem: '没有可选项的题目' }],
        }),
      }
      throw new Error(`未模拟请求：${path} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(StudentQuizView)
    await flushPromises()

    expect(wrapper.text()).toContain('题目缺少可作答选项，暂不能提交。')
    expect((wrapper.get('[data-testid="assignment-task-assignment-empty-options"] button.yk-button.primary').element as HTMLButtonElement).disabled).toBe(true)
  })

  it('学生从本人任务读取服务端冻结题目，并仅按题目引用提交动态作答', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/v1/assignments/my') return { ok: true, json: async () => ({ items: [{ assignment_id: 'assignment-a', title: '真实作业', status: 'PUBLISHED' }] }) }
      if (path === '/api/v1/quizzes/my') return { ok: true, json: async () => ({ items: [{ quiz_id: 'quiz-a', title: '真实测验', status: 'PUBLISHED' }] }) }
      if (path === '/api/v1/assignments/assignment-a/student-task') return { ok: true, json: async () => ({ assignment_id: 'assignment-a', title: '真实作业', status: 'PUBLISHED', questions: [{ question_ref_id: 'assignment-ref-live', ...publishedQuestion }] }) }
      if (path === '/api/v1/quizzes/quiz-a/student-task') return { ok: true, json: async () => ({ quiz_id: 'quiz-a', title: '真实测验', status: 'PUBLISHED', time_limit_minutes: 10, questions: [{ question_ref_id: 'quiz-ref-live', ...publishedQuestion }] }) }
      if (path === '/api/v1/assignments/assignment-a/submit') return { ok: true, json: async () => ({ submission_id: 'submission-a' }) }
      if (path === '/api/v1/quizzes/quiz-a/attempts') return { ok: true, json: async () => ({ attempt_id: 'attempt-a' }) }
      if (path === '/api/v1/quizzes/quiz-a/attempts/attempt-a/submit') return { ok: true, json: async () => ({ attempt_id: 'attempt-a' }) }
      throw new Error(`未模拟请求：${path} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(StudentQuizView)
    await flushPromises()

    await wrapper.get('[data-testid="student-question-assignment-assignment-a-assignment-ref-live"] button[role="radio"]').trigger('click')
    await wrapper.get('[data-testid="student-question-quiz-quiz-a-quiz-ref-live"] button[role="radio"]').trigger('click')
    await wrapper.get('[data-testid="assignment-task-assignment-a"] button.yk-button.primary').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="quiz-task-quiz-a"] button.yk-button.primary').trigger('click')
    await flushPromises()

    expect(fetchMock.mock.calls.some(([path]) => String(path) === '/api/v1/assignments/my')).toBe(true)
    expect(fetchMock.mock.calls.some(([path]) => String(path) === '/api/v1/assignments/assignment-a/student-task')).toBe(true)
    expect(fetchMock.mock.calls.some(([path]) => String(path) === '/api/v1/quizzes/my')).toBe(true)
    expect(fetchMock.mock.calls.some(([path]) => String(path) === '/api/v1/quizzes/quiz-a/student-task')).toBe(true)
    const writes = fetchMock.mock.calls.filter(([path]) => String(path).endsWith('/submit'))
    expect(writes).toHaveLength(2)
    expect(JSON.parse(String(writes[0][1]?.body))).toEqual({ answers: { 'assignment-ref-live': 'A' } })
    expect(JSON.parse(String(writes[1][1]?.body))).toEqual({ answers: { 'quiz-ref-live': 'A' } })
    for (const [, init] of writes) {
      const payload = JSON.parse(String(init?.body))
      expect(payload).not.toHaveProperty('raw_score')
      expect(payload).not.toHaveProperty('max_score')
      expect(payload).not.toHaveProperty('source_proof')
      expect(payload).not.toHaveProperty('question_snapshot')
      expect(payload).not.toHaveProperty('question_version')
    }
  })
})
