import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CourseResourcesView from './CourseResourcesView.vue'

const theory = Array.from({ length: 37 }, (_, index) => ({ course_id: 'course_data_security', lesson_id: `t${index}`, lesson_kind: 'THEORY', chapter_no: index < 5 ? 1 : index < 8 ? 2 : index < 14 ? 3 : index < 21 ? 4 : index < 28 ? 5 : index < 33 ? 6 : 7, lesson_code: index === 36 ? '7.4' : `课时${index + 1}`, title: index === 36 ? '典型数据安全产品选型指南（加密类/脱敏类/审计类/管控类/备份类）' : `知识点${index + 1}`, purpose: null, environment: null, principle: null, steps_summary: null, core_experiment: null }))
const labs = Array.from({ length: 12 }, (_, index) => ({ course_id: 'course_data_security', lesson_id: `l${index}`, lesson_kind: 'LAB', chapter_no: null, lesson_code: `实验${String(index + 1).padStart(2, '0')}`, title: `实验主题${index + 1}`, purpose: '实验目的', environment: '隔离环境', principle: '实验原理', steps_summary: '实验步骤', core_experiment: index < 2 ? 'AES/DES' : '综合实践' }))

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
      if (path.includes('readiness')) return new Response(JSON.stringify({ course_id: 'course_data_security', theory_lessons: 37, lab_lessons: 12, ppt: { ready: 0, required: 37 }, theory_video: { ready: 0, required: 37 }, lab_file: { ready: 0, required: 12 }, lab_video: { ready: 0, required: 12 }, question_lessons: { ready: 0, required: 49 }, published_questions: { ready: 0, required: 196 }, blocking: 196 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
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
})
