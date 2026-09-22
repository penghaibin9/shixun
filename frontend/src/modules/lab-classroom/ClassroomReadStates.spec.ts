import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  classroomApi: vi.fn(),
  subscribeClassroomEvents: vi.fn(),
}))

vi.mock('../../app/api', () => ({
  classroomApi: mocks.classroomApi,
  subscribeClassroomEvents: mocks.subscribeClassroomEvents,
}))

import LabLiveView from './LabLiveView.vue'
import TeacherInstancesView from './TeacherInstancesView.vue'
import TeacherLogsView from './TeacherLogsView.vue'

afterEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

beforeEach(() => {
  mocks.subscribeClassroomEvents.mockReturnValue(() => {})
})

test('教师课堂权限失败后清除旧统计和旧处置入口', async () => {
  let rejected = false
  mocks.classroomApi.mockImplementation((path: string) => {
    if (rejected) return Promise.reject({ code: 'AUTH.SCOPE_DENIED', message: '无权访问该班级' })
    if (path.endsWith('/summary')) return Promise.resolve({ started: 1, completed: 0, running: 1, failed: 0, not_started: 42, data_status: 'READY' })
    if (path.endsWith('/students')) return Promise.resolve({ items: [{ student_id: 'student-a', student_name: '张同学', status: 'RUNNING', current_step: 2, total_steps: 6, raw_score: 20, max_score: 100, runtime_instance_id: 'runtime-a' }] })
    return Promise.resolve({})
  })
  const wrapper = mount(LabLiveView)
  await flushPromises()
  expect(wrapper.text()).toContain('已启动')
  expect(wrapper.text()).toContain('张同学')

  rejected = true
  await wrapper.get('button').trigger('click')
  await flushPromises()

  expect(wrapper.text()).toContain('无权访问该班级')
  expect(wrapper.text()).not.toContain('已启动')
  expect(wrapper.text()).not.toContain('张同学')
  expect(wrapper.text()).not.toContain('提醒未活动学生')
  wrapper.unmount()
})

test('教师实例刷新失败后不把旧运行记录当作当前事实', async () => {
  let rejected = false
  mocks.classroomApi.mockImplementation((path: string) => {
    if (rejected) return Promise.reject({ code: 'DEPENDENCY.UNAVAILABLE', message: '运行服务暂不可用' })
    if (path.endsWith('/students')) return Promise.resolve({ items: [{ student_id: 'student-a', student_name: '李同学', status: 'RUNNING', runtime_instance_id: 'runtime-a' }] })
    return Promise.resolve({})
  })
  const wrapper = mount(TeacherInstancesView)
  await flushPromises()
  expect(wrapper.text()).toContain('李同学')
  expect(wrapper.text()).toContain('已启动')

  rejected = true
  await wrapper.get('button').trigger('click')
  await flushPromises()

  expect(wrapper.text()).toContain('运行服务暂不可用')
  expect(wrapper.text()).not.toContain('李同学')
  expect(wrapper.text()).not.toContain('已启动')
  expect(wrapper.find('button.danger').exists()).toBe(false)
  wrapper.unmount()
})

test('日志读取失败后撤销旧目标名单，不能继续提交分发', async () => {
  let rejected = false
  mocks.classroomApi.mockImplementation((path: string) => {
    if (rejected) return Promise.reject({ code: 'AUTH.FORBIDDEN', message: '没有查看教学日志的权限' })
    if (path.includes('/teaching-logs/audit')) return Promise.resolve({ items: [{ event_id: 'event-a', event_type: 'runtime.command' }] })
    if (path.endsWith('/teaching-logs/distributions')) return Promise.resolve({ items: [] })
    if (path.endsWith('/students')) return Promise.resolve({ items: [{ student_id: 'student-a', student_name: '王同学' }] })
    return Promise.resolve({})
  })
  const wrapper = mount(TeacherLogsView)
  await flushPromises()
  expect(wrapper.get('[role="checkbox"]').exists()).toBe(true)
  await wrapper.get('[role="checkbox"]').trigger('click')
  expect(wrapper.get('button.primary').attributes('disabled')).toBeUndefined()

  rejected = true
  await wrapper.get('button').trigger('click')
  await flushPromises()

  expect(wrapper.text()).toContain('没有查看教学日志的权限')
  expect(wrapper.find('form').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('王同学')
  wrapper.unmount()
})
