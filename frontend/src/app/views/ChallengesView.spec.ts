import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ChallengesView from './ChallengesView.vue'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

const checkpointChallenge = {
  challenge_id: 'challenge_web_08',
  course_id: 'course_web_security',
  lesson_id: 'lesson_web_08',
  lab_definition_id: 'lab_web_08',
  lab_version_id: 'lab-version-08',
  checkpoint_key: 'cp_web08_solution',
  prerequisite_challenge_id: null,
  unlocked: true,
  title: 'API 对象级权限测试',
  description: '验证对象级权限。',
  difficulty: 'BEGINNER',
  max_attempts: 10,
  validation_mode: 'CHECKPOINT_ONLY',
  status: 'PUBLISHED',
  flag_configured: false,
}

describe('挑战验证方式', () => {
  it('学生查看 CHECKPOINT_ONLY 挑战时不要求输入 Flag', async () => {
    localStorage.setItem('yk-course-id', 'course_web_security')
    localStorage.setItem('yk-class-id', 'class-web')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path === '/api/v1/auth/context') {
        return json({
          user_id: 'student-web',
          role: 'student',
          teacher_id: null,
          student_id: 'student-web',
          permissions: ['classroom.lab.read', 'classroom.lab.start'],
          course_ids: ['course_web_security'],
          class_ids: ['class-web'],
        })
      }
      if (path.startsWith('/api/v1/challenges?')) return json({ items: [checkpointChallenge], total: 1 })
      if (path.includes('/hints')) return json({ items: [], attempts: 0, total: 0 })
      throw new Error(`unexpected request: ${path}`)
    }))

    const wrapper = mount(ChallengesView)
    await flushPromises()
    await wrapper.get('.challenge-row').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Checkpoint 判定')
    expect(wrapper.text()).toContain('仅使用权威 Checkpoint，不需要 Flag')
    expect(wrapper.find('.flag-box input').exists()).toBe(false)
    expect(wrapper.get('.flag-box button').text()).toBe('验证当前 Checkpoint')
  })

  it('教师查看 CHECKPOINT_ONLY 挑战时不会出现配置 Flag 操作', async () => {
    localStorage.setItem('yk-course-id', 'course_web_security')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path === '/api/v1/auth/context') {
        return json({
          user_id: 'teacher-web',
          role: 'teacher',
          teacher_id: 'teacher-web',
          student_id: null,
          permissions: ['labs.read', 'labs.write'],
          course_ids: ['course_web_security'],
          class_ids: [],
        })
      }
      if (path.startsWith('/api/v1/challenges?')) return json({ items: [checkpointChallenge], total: 1 })
      if (path.includes('/hints')) return json({ items: [], attempts: 0, total: 0 })
      throw new Error(`unexpected request: ${path}`)
    }))

    const wrapper = mount(ChallengesView)
    await flushPromises()
    await wrapper.get('.challenge-row').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('本挑战不配置 Flag')
    expect(wrapper.text()).not.toContain('安全保存 Flag')
    expect(wrapper.find('.flag-box input').exists()).toBe(false)
  })
})
