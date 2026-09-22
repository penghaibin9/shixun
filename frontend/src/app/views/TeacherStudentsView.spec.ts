import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TeacherStudentsView from './TeacherStudentsView.vue'

vi.mock('vue-router', () => ({ RouterLink: { template: '<a><slot /></a>' } }))

const ok = (body: unknown) => ({ ok: true, json: async () => body, blob: async () => new Blob(['xlsx']) })

describe('教师学生管理', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('yk-class-id', 'class-a')
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:student-errors') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('跨班拒绝时显示明确无权限状态', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => ({ code: 'AUTH.SCOPE_DENIED', message: '不能访问该班级', request_id: 'req-test', details: {} }) }))
    const wrapper = mount(TeacherStudentsView, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()
    expect(wrapper.text()).toContain('无权限查看该班级')
  })

  it('导入存在错误行时提供独立 XLSX 下载入口', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/v1/courses') return ok({ items: [] })
      if (path === '/api/v1/classes') return ok({ items: [{ class_id: 'class-a', name: '测试班' }] })
      if (path.includes('/members/import') && init?.method === 'POST') return ok({ job_id: 'job-errors', success_count: 1, failure_count: 2, duplicate_count: 1 })
      if (path === '/api/v1/import-jobs/job-errors/error-rows.xlsx') return ok({})
      if (path.includes('/members?')) return ok({ items: [], total: 0 })
      throw new Error(`未模拟请求：${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const wrapper = mount(TeacherStudentsView, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()

    const input = wrapper.get('input[aria-label="导入学生名单"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [new File(['xlsx'], 'students.xlsx')] })
    await input.trigger('change')
    const importButton = wrapper.findAll('button').find(button => button.text() === '导入学生')
    await importButton?.trigger('click')
    await vi.waitFor(() => expect(wrapper.find('[data-testid="student-import-error-download"]').exists()).toBe(true))
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/classes/class-a/members/import', expect.objectContaining({
      headers: expect.objectContaining({ 'Idempotency-Key': 'members-1c980b22bca31941462855e560db3053e7772efb4b8bc7c4d5d8bb799a1abc6c' }),
    }))
    const errorButton = wrapper.get('[data-testid="student-import-error-download"]')
    expect(errorButton.text()).toContain('下载逐行错误文件')
    await errorButton.trigger('click')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/import-jobs/job-errors/error-rows.xlsx', expect.any(Object))
    expect(URL.createObjectURL).toHaveBeenCalled()
  })

  it('新增已有学生只提交学号和姓名，由服务端解析权威档案', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/v1/courses') return ok({ items: [] })
      if (path === '/api/v1/classes') return ok({ items: [{ class_id: 'class-a', name: '测试班' }] })
      if (path.includes('/members?')) return ok({ items: [], total: 0 })
      if (path === '/api/v1/classes/class-a/members' && init?.method === 'POST') return ok({ class_membership_id: 'member-a' })
      throw new Error(`未模拟请求：${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('prompt', vi.fn().mockReturnValueOnce('20260001').mockReturnValueOnce('张三'))
    const wrapper = mount(TeacherStudentsView, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('新增已有学生'))?.trigger('click')
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/classes/class-a/members',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ student_number: '20260001', student_name: '张三' }) }),
    ))
  })
})
