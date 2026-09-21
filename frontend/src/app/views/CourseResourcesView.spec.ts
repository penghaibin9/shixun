import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CourseResourcesView from './CourseResourcesView.vue'

const theory = Array.from({ length: 37 }, (_, index) => ({ course_id: 'course_data_security', lesson_id: `t${index}`, lesson_kind: 'THEORY', chapter_no: index < 5 ? 1 : index < 8 ? 2 : index < 14 ? 3 : index < 21 ? 4 : index < 28 ? 5 : index < 33 ? 6 : 7, lesson_code: index === 36 ? '7.4' : `课时${index + 1}`, title: index === 36 ? '典型数据安全产品选型指南（加密类/脱敏类/审计类/管控类/备份类）' : `知识点${index + 1}`, purpose: null, environment: null, principle: null, steps_summary: null, core_experiment: null }))
const labs = Array.from({ length: 12 }, (_, index) => ({ course_id: 'course_data_security', lesson_id: `l${index}`, lesson_kind: 'LAB', chapter_no: null, lesson_code: `实验${String(index + 1).padStart(2, '0')}`, title: `实验主题${index + 1}`, purpose: '实验目的', environment: '隔离环境', principle: '实验原理', steps_summary: '实验步骤', core_experiment: index < 2 ? 'AES/DES' : '综合实践' }))
const readiness = { course_id: 'course_data_security', theory_lessons: 37, lab_lessons: 12, ppt: { ready: 0, required: 37 }, theory_video: { ready: 0, required: 37 }, lab_file: { ready: 0, required: 12 }, lab_video: { ready: 0, required: 12 }, question_lessons: { ready: 0, required: 49 }, published_questions: { ready: 0, required: 196 }, blocking: 196 }
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

async function mountQuestions() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/course-questions', component: CourseResourcesView, meta: { page: 'questions' } }] })
  await router.push('/course-questions'); await router.isReady()
  const wrapper = mount(CourseResourcesView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

afterEach(() => vi.restoreAllMocks())
describe('课程资源页面', () => {
  it('从接口渲染 37/12 蓝图而非前端写死完成状态', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => new Response(JSON.stringify(String(input).includes('course-blueprint') ? { items: [...theory, ...labs], total: 49, chapter_counts: {} } : { items: [], total: 0 }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/course-blueprint', component: CourseResourcesView, meta: { page: 'blueprint' } }] })
    await router.push('/course-blueprint'); await router.isReady()
    const wrapper = mount(CourseResourcesView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('37 个理论课时')
    expect(wrapper.text()).toContain('7.4')
    expect(wrapper.text()).toContain('典型数据安全产品选型指南')
    expect(wrapper.findAll('tbody tr')).toHaveLength(37)
  })

  it('通过上传弹窗建立真实文件草稿版本', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.includes('course-blueprint')) return new Response(JSON.stringify({ items: [...theory, ...labs], total: 49, chapter_counts: {} }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.includes('readiness')) return new Response(JSON.stringify(readiness), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.endsWith('/resources/files')) return new Response(JSON.stringify({ file_id: 'file-1', original_name: 'lesson.pptx', mime_type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', size_bytes: 8, sha256: 'a'.repeat(64) }), { status: 201, headers: { 'Content-Type': 'application/json' } })
      if (path.endsWith('/resources') && init?.method === 'POST') return new Response(JSON.stringify({ resource_id: 'resource-1', course_id: 'course_data_security', lesson_id: 't0', name: '第一课讲义', resource_type: 'PPT', status: 'DRAFT', created_at: '', latest_version: null }), { status: 201, headers: { 'Content-Type': 'application/json' } })
      if (path.includes('/versions')) return new Response(JSON.stringify({ resource_version_id: 'version-1', version_no: 1, file_id: 'file-1', status: 'DRAFT', sha256: 'a'.repeat(64) }), { status: 201, headers: { 'Content-Type': 'application/json' } })
      return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/resources', component: CourseResourcesView, meta: { page: 'overview' } }] })
    await router.push('/resources'); await router.isReady()
    const wrapper = mount(CourseResourcesView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.get('button.primary').trigger('click')
    await wrapper.get('input[placeholder="例如：第 1.1 课时演示文稿"]').setValue('第一课讲义')
    const fileInput = wrapper.get('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [new File([new Uint8Array([1, 2, 3])], 'lesson.pptx')], configurable: true })
    await fileInput.trigger('change')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const uploadCall = fetchMock.mock.calls.find(call => String(call[0]).endsWith('/resources/files'))
    expect(uploadCall?.[1]?.body).toBeInstanceOf(FormData)
    expect(wrapper.text()).toContain('真实文件已上传并登记为草稿版本')
  })

  it('下载模板并只接收 XLSX 题库文件，逐行显示导入错误', async () => {
    const job = { job_id: 'job-196', status: 'VALIDATION_FAILED', total_count: 196, imported_count: 0, error_count: 2, review_queue_count: 0, original_filename: 'questions.xlsx', error_rows: [{ row_number: 8, field: '课时编号', code: 'UNKNOWN_LESSON', message: '课时编号不存在' }, { row_number: 19, field: '正确答案*', code: 'ANSWER_REQUIRED', message: '答案不能为空' }] }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.includes('import-template.xlsx')) return new Response(new Uint8Array([80, 75, 3, 4]), { status: 200, headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' } })
      if (path.endsWith('/questions/import') && init?.method === 'POST') return json(job, 201)
      if (path.includes('/questions/import-jobs/job-196')) return json(job)
      if (path.includes('course-blueprint')) return json({ items: [...theory, ...labs], total: 49, chapter_counts: {} })
      if (path.includes('resources/readiness')) return json(readiness)
      if (path.includes('questions/coverage')) return json({ items: [], total: 49, passed: 0 })
      if (path.includes('questions/review-queue')) return json({ items: [], page: 1, page_size: 0, total: 0 })
      return json({ items: [], total: 0 })
    })
    vi.stubGlobal('fetch', fetchMock)
    const createUrl = vi.fn(() => 'blob:question-template'), revokeUrl = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { value: createUrl, configurable: true })
    Object.defineProperty(URL, 'revokeObjectURL', { value: revokeUrl, configurable: true })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const wrapper = await mountQuestions()

    await wrapper.findAll('button').find(button => button.text() === '下载 XLSX（电子表格）模板')!.trigger('click')
    await flushPromises()
    expect(fetchMock.mock.calls.some(call => String(call[0]).includes('/questions/import-template.xlsx?course_id=course_data_security'))).toBe(true)
    expect(revokeUrl).toHaveBeenCalledWith('blob:question-template')

    await wrapper.findAll('button').find(button => button.text() === '批量导入题目')!.trigger('click')
    const input = wrapper.get('input[aria-label="选择题库文件"]')
    Object.defineProperty(input.element, 'files', { value: [new File(['bad'], 'questions.csv', { type: 'text/csv' })], configurable: true })
    await input.trigger('change')
    expect(wrapper.text()).toContain('仅支持 XLSX（电子表格）文件')

    Object.defineProperty(input.element, 'files', { value: [new File([new Uint8Array([80, 75, 3, 4])], 'questions.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', lastModified: 1 })], configurable: true })
    await input.trigger('change')
    await wrapper.findAll('form').find(form => form.text().includes('导入 196 行题库数据'))!.trigger('submit')
    await flushPromises()
    const importCall = fetchMock.mock.calls.find(call => String(call[0]).endsWith('/questions/import'))
    expect(importCall?.[1]?.body).toBeInstanceOf(FormData)
    expect(new Headers(importCall?.[1]?.headers).get('Idempotency-Key')).toContain('questions-questions.xlsx')
    expect(wrapper.text()).toContain('文件数据行196')
    expect(wrapper.text()).toContain('第 8 行')
    expect(wrapper.text()).toContain('课时编号不存在')
    expect(wrapper.text()).toContain('第 19 行')
    expect(wrapper.text()).not.toContain('UNKNOWN_LESSON')
  })

  it('独立审核队列禁止创建人自审并支持填写原因后驳回', async () => {
    const queue = { items: [
      { question_id: 'q-own', lesson_id: 't0', lesson_code: '1.1', question_type: 'SINGLE', stem: '本人创建题', options: [], answer: ['A'], explanation: '解析', status: 'PENDING_REVIEW', created_by: 'teacher_b', created_at: '2026-09-21T10:00:00' },
      { question_id: 'q-other', lesson_id: 't0', lesson_code: '1.1', question_type: 'TRUE_FALSE', stem: '他人创建题', options: [], answer: ['正确'], explanation: '完整解析', status: 'PENDING_REVIEW', created_by: 'teacher_a', created_at: '2026-09-21T10:01:00', source_row_number: 3 },
    ], page: 1, page_size: 2, total: 2 }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.includes('course-blueprint')) return json({ items: [...theory, ...labs], total: 49, chapter_counts: {} })
      if (path.includes('resources/readiness')) return json(readiness)
      if (path.includes('questions/coverage')) return json({ items: [], total: 49, passed: 0 })
      if (path.includes('questions/review-queue')) return json(queue)
      if (path.endsWith('/questions/q-other/review') && init?.method === 'POST') return json({ question_id: 'q-other', status: 'REJECTED', reviewed_by: 'teacher_b' })
      return json({ items: [], total: 0 })
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountQuestions()
    await wrapper.findAll('[role="tab"]').find(tab => tab.text().includes('待审核'))!.trigger('click')
    const rows = wrapper.findAll('tbody tr')
    const ownRow = rows.find(row => row.text().includes('本人创建题'))!, otherRow = rows.find(row => row.text().includes('他人创建题'))!
    expect(ownRow.text()).toContain('需其他审核人')
    expect(ownRow.find('button').exists()).toBe(false)
    await otherRow.get('button').trigger('click')
    const drawer = wrapper.get('[aria-label="题目独立审核"]')
    await drawer.findAll('[role="radio"]')[1].trigger('click')
    await drawer.get('form').trigger('submit')
    expect(wrapper.text()).toContain('驳回时必须填写原因')
    expect(fetchMock.mock.calls.some(call => String(call[0]).endsWith('/questions/q-other/review'))).toBe(false)
    await drawer.get('textarea').setValue('答案表述不准确，请修正。')
    await drawer.get('form').trigger('submit')
    await flushPromises()
    const reviewCall = fetchMock.mock.calls.find(call => String(call[0]).endsWith('/questions/q-other/review'))
    expect(JSON.parse(String(reviewCall?.[1]?.body))).toEqual({ decision: 'REJECTED', comment: '答案表述不准确，请修正。' })
    expect(wrapper.text()).toContain('题目已驳回并退回修改')
  })
})
