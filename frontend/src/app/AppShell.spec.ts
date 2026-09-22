import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import AppShell from './AppShell.vue'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('应用壳层', () => {
  it('只展示服务端确认角色可见的入口', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      user_id: 'teacher-1', role: 'teacher', teacher_id: 'teacher-1', student_id: null,
      permissions: ['teaching.dashboard.read'], course_ids: ['course-1'], class_ids: ['class-1'],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    const wrapper = mount(AppShell, { global: { stubs: { RouterLink: { props: ['to'], template: '<a><slot /></a>' } } } })
    await flushPromises()

    expect(wrapper.get('[data-testid="app-shell-role"]').text()).toContain('教师')
    expect(wrapper.text()).toContain('教师工作台')
    expect(wrapper.text()).not.toContain('学生首页')
    expect(wrapper.text()).not.toContain('运行总览')
  })

  it('会话读取失败时不回退为验收视角或全量导航', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ code: 'AUTH.TRUSTED_IDENTITY_REQUIRED', message: '需要可信身份' }), { status: 401, headers: { 'Content-Type': 'application/json' } })))

    const wrapper = mount(AppShell, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()

    expect(wrapper.get('[data-testid="app-shell-session-error"]').text()).toContain('需要可信身份')
    expect(wrapper.text()).toContain('教学闭环')
    expect(wrapper.text()).not.toContain('教师工作台')
  })
})
