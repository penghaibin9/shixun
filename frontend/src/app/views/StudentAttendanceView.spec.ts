import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import StudentAttendanceView from './StudentAttendanceView.vue'

const routeState = vi.hoisted(() => ({ token: 'cross-device-token-1234567890' }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: routeState }) }))

describe('学生独立签到链接', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('yk-student-id', 'student-a')
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('只依赖当前路由令牌解析并提交签到，不读取教师任务状态', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ task_id: 'task-a', title: 'RSA 课堂签到', task_type: 'CLASSROOM', starts_at: '2026-09-21T08:00:00', expires_at: '2026-09-21T09:00:00', status: 'PUBLISHED' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ record_id: 'record-a' }) })
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mount(StudentAttendanceView)
    await flushPromises()
    expect(wrapper.text()).toContain('RSA 课堂签到')
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('签到成功')
    expect(localStorage.getItem('yk-attendance-id')).toBeNull()
    expect(localStorage.getItem('yk-sign-token')).toBeNull()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/attendance/sign-links/cross-device-token-1234567890')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/attendance/sign-links/cross-device-token-1234567890/sign')
  })
})
