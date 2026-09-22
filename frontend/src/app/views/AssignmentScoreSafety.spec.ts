import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import StudentQuizView from './StudentQuizView.vue'
import TeacherAssignmentsView from './TeacherAssignmentsView.vue'

describe('作业与测验服务端评分请求', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('yk-course-id', 'course-a')
    localStorage.setItem('yk-class-id', 'class-a')
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('教师只选择题目，不把题目快照、版本或分值交给浏览器', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/v1/assignments') return { ok: true, json: async () => ({ assignment_id: 'assignment-a' }) }
      if (path === '/api/v1/assignments/assignment-a/publish') return { ok: true, json: async () => ({ status: 'PUBLISHED' }) }
      if (path === '/api/v1/quizzes') return { ok: true, json: async () => ({ quiz_id: 'quiz-a' }) }
      if (path === '/api/v1/quizzes/quiz-a/publish') return { ok: true, json: async () => ({ status: 'PUBLISHED' }) }
      throw new Error(`未模拟请求：${path} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(TeacherAssignmentsView)
    await wrapper.find('button.yk-button.primary').trigger('click')
    await flushPromises()

    const assignmentCall = fetchMock.mock.calls.find(([path]) => String(path) === '/api/v1/assignments')
    const quizCall = fetchMock.mock.calls.find(([path]) => String(path) === '/api/v1/quizzes')
    for (const call of [assignmentCall, quizCall]) {
      const payload = JSON.parse(String(call?.[1]?.body))
      expect(payload.questions).toEqual([{ question_id: 'question-b-rsa-1' }])
      expect(payload).not.toHaveProperty('raw_score')
      expect(payload).not.toHaveProperty('max_score')
      expect(payload.questions[0]).not.toHaveProperty('question_snapshot')
      expect(payload.questions[0]).not.toHaveProperty('question_version')
    }
  })

  it('学生只提交作答，不提交分数或评分证明', async () => {
    localStorage.setItem('yk-assignment-id', 'assignment-a')
    localStorage.setItem('yk-quiz-id', 'quiz-a')
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/v1/assignments/assignment-a/submit') return { ok: true, json: async () => ({ submission_id: 'submission-a' }) }
      if (path === '/api/v1/quizzes/quiz-a/attempts') return { ok: true, json: async () => ({ attempt_id: 'attempt-a' }) }
      if (path === '/api/v1/quizzes/quiz-a/attempts/attempt-a/submit') return { ok: true, json: async () => ({ attempt_id: 'attempt-a' }) }
      throw new Error(`未模拟请求：${path} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(StudentQuizView)
    await wrapper.find('button.yk-button.primary').trigger('click')
    await flushPromises()

    const writes = fetchMock.mock.calls.filter(([path]) => String(path).endsWith('/submit'))
    expect(writes).toHaveLength(2)
    for (const [, init] of writes) {
      const payload = JSON.parse(String(init?.body))
      expect(payload).toHaveProperty('answers')
      expect(payload).not.toHaveProperty('raw_score')
      expect(payload).not.toHaveProperty('max_score')
      expect(payload).not.toHaveProperty('source_proof')
    }
  })
})
