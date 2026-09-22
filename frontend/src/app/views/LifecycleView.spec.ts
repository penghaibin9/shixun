import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import LifecycleView from './LifecycleView.vue'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('教学闭环页', () => {
  it('显示会话授权入口，不把流程清单伪装成完成状态', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      user_id: 'teacher-1', role: 'teacher', teacher_id: 'teacher-1', student_id: null,
      permissions: ['teaching.course.write', 'teaching.members.import', 'resources:read', 'teaching.attendance.write', 'labs.publish', 'grading:read', 'analytics:class', 'archives:read'],
      course_ids: ['course-1'], class_ids: ['class-1'],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    const wrapper = mount(LifecycleView, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()

    expect(wrapper.get('[data-testid="lifecycle-list"]').text()).toContain('创建课程')
    expect(wrapper.text()).toContain('当前身份可办理')
    expect(wrapper.text()).not.toContain('待业务模块接入')
    expect(wrapper.text()).toContain('不把本页当作业务完成或验收结论')
  })

  it('读取失败时明确不能推断业务完成状态', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ code: 'AUTH.UNAUTHENTICATED', message: '身份未确认' }), { status: 401, headers: { 'Content-Type': 'application/json' } })))

    const wrapper = mount(LifecycleView, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()

    expect(wrapper.get('[data-testid="lifecycle-error"]').text()).toContain('无法据此判断任何业务步骤是否完成')
  })
})
