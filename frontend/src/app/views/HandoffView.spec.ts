import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import HandoffView from './HandoffView.vue'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('协作交接页', () => {
  it('仅展示服务端解析的会话范围', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      user_id: 'student-1', role: 'student', teacher_id: null, student_id: 'student-1',
      permissions: ['teaching.student.read'], course_ids: ['course-1'], class_ids: ['class-1', 'class-2'],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    const wrapper = mount(HandoffView)
    await flushPromises()

    expect(wrapper.get('[data-testid="handoff-context"]').text()).toContain('学生')
    expect(wrapper.text()).toContain('1 门')
    expect(wrapper.text()).toContain('2 个')
  })

  it('读取失败时不显示未经确认的交接范围', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ code: 'AUTH.UNAUTHENTICATED', message: '身份未确认' }), { status: 401, headers: { 'Content-Type': 'application/json' } })))

    const wrapper = mount(HandoffView)
    await flushPromises()

    expect(wrapper.get('[data-testid="handoff-error"]').text()).toContain('不把未确认的会话视为可交接状态')
    expect(wrapper.find('[data-testid="handoff-context"]').exists()).toBe(false)
  })
})
