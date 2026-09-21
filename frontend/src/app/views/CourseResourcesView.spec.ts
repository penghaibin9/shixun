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
})
