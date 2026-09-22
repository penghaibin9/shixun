import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import TeacherDashboard from './TeacherDashboard.vue'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('教师工作台', () => {
  it('读取服务端教学读模型，而不是展示写死统计', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      course_count: 2, class_count: 3, student_count: 43, open_attendance_count: 1,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    const wrapper = mount(TeacherDashboard, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()

    expect(wrapper.get('[data-testid="teacher-dashboard-summary"]').text()).toContain('43')
    expect(wrapper.text()).toContain('正在签到')
    expect(wrapper.get('[data-testid="teacher-dashboard-next-action"]').text()).toContain('查看签到进展')
    expect(fetch).toHaveBeenCalledWith('/api/v1/teaching/read-model', expect.objectContaining({ headers: expect.any(Object) }))
  })

  it('读取失败时明确显示错误，而不回退为虚构数据', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ code: 'AUTH.SCOPE_DENIED', message: '无权读取教学工作台' }), { status: 403, headers: { 'Content-Type': 'application/json' } })))

    const wrapper = mount(TeacherDashboard, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()

    expect(wrapper.get('[data-testid="teacher-dashboard-error"]').text()).toContain('无权读取教学工作台')
    expect(wrapper.find('[data-testid="teacher-dashboard-summary"]').exists()).toBe(false)
  })
})
