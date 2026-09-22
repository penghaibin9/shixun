import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import StudentHome from './StudentHome.vue'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('学生首页', () => {
  it('只渲染后端返回的本人签到任务', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      class_count: 1,
      open_attendance: [{ task_id: 'att-1', title: 'RSA 课堂签到', expires_at: '2026-09-22T15:00:00' }],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    const wrapper = mount(StudentHome, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()

    expect(wrapper.get('[data-testid="student-home-summary"]').text()).toContain('1')
    expect(wrapper.get('[data-testid="student-home-attendance-task"]').text()).toContain('RSA 课堂签到')
    expect(fetch).toHaveBeenCalledWith('/api/v1/teaching/student-read-model', expect.objectContaining({ headers: expect.any(Object) }))
  })

  it('没有任务时展示真实空状态', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ class_count: 1, open_attendance: [] }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    const wrapper = mount(StudentHome, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()

    expect(wrapper.get('[data-testid="student-home-empty"]').text()).toContain('当前没有已发布')
  })
})
