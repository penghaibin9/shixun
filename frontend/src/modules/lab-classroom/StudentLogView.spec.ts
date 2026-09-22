import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import StudentLogView from './StudentLogView.vue'

const assignment = {
  assignment_id: 'assignment-a', status: 'ASSIGNED', assigned_at: '2026-09-22T10:00:00Z',
  distribution: { title: '流量分析任务', instruction: '分析真实网络流量', distribution_type: 'TRAFFIC' },
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('yk-student-id', 'student-a')
  localStorage.setItem('yk-course-id', 'course-a')
  localStorage.setItem('yk-class-id', 'class-a')
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:runtime-logs') })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
})

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear() })

test('学生使用可信身份请求真实日志压缩包而不是打开无身份新标签', async () => {
  let listLoads = 0
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path === '/api/v1/teaching-logs/my-assignments') {
      listLoads += 1
      return { ok: true, json: async () => ({ items: [assignment] }) }
    }
    if (path === '/api/v1/teaching-logs/my-assignments/assignment-a/download') {
      return { ok: true, json: async () => ({ download_url: '/api/v1/artifact-storage/bundles/assignment-a?capability=signed' }) }
    }
    if (path.startsWith('/api/v1/artifact-storage/bundles/assignment-a')) {
      return { ok: true, blob: async () => new Blob(['PK-real-zip'], { type: 'application/zip' }) }
    }
    throw new Error(`未模拟请求：${path}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  const wrapper = mount(StudentLogView)
  await flushPromises()
  await wrapper.get('[data-testid="assignment-download"]').trigger('click')
  await flushPromises()

  const bundleCall = fetchMock.mock.calls.find(call => String(call[0]).startsWith('/api/v1/artifact-storage/bundles/assignment-a'))
  expect(bundleCall?.[1]?.headers).toEqual(expect.objectContaining({
    'X-Role': 'student', 'X-Student-Id': 'student-a', 'X-Course-Ids': 'course-a', 'X-Class-Ids': 'class-a',
  }))
  expect(URL.createObjectURL).toHaveBeenCalled()
  expect(click).toHaveBeenCalled()
  expect(listLoads).toBe(2)
})
