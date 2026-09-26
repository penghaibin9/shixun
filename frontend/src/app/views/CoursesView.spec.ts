import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CoursesView from './CoursesView.vue'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('课程选择', () => {
  it('展示后端真实课时统计并将选择保存为当前课程', async () => {
    localStorage.setItem('yk-course-id', 'course-a')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      const body = path.includes('/course-catalogs')
        ? { items: [
            { catalog_key: 'data_security_v1', name: '数据安全技术基础', theory_lessons: 37, lab_lessons: 12, question_types: ['FILL', 'SINGLE', 'MULTIPLE', 'TRUE_FALSE'], resource_minimums: { questions_per_lesson: 4 } },
            { catalog_key: 'web_security_v1', name: 'Web 应用安全实训', theory_lessons: 12, lab_lessons: 12, question_types: ['FILL', 'SINGLE', 'MULTIPLE', 'TRUE_FALSE'], resource_minimums: { questions_per_lesson: 4 } },
          ] }
        : { items: [
            { course_id: 'course-a', catalog_key: 'data_security_v1', name: '数据安全基础', term: '2026 秋季', status: 'ACTIVE', theory_lesson_count: 37, lab_lesson_count: 12 },
            { course_id: 'course-b', catalog_key: 'web_security_v1', name: '安全运营专题', term: '2027 春季', status: 'DRAFT', theory_lesson_count: 18, lab_lesson_count: 7 },
          ] }
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))

    const wrapper = mount(CoursesView)
    await flushPromises()
    expect(wrapper.text()).toContain('Web 应用安全实训 · 12+12 课时')
    const first = wrapper.get('[data-testid="course-course-a"]')
    const second = wrapper.get('[data-testid="course-course-b"]')
    expect(first.attributes('aria-pressed')).toBe('true')
    expect(first.text()).toContain('37 理论课时 · 12 实验课时')
    expect(second.text()).toContain('18 理论课时 · 7 实验课时')

    await second.trigger('click')
    expect(localStorage.getItem('yk-course-id')).toBe('course-b')
    expect(second.attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-testid="message"]').text()).toContain('已选择课程：安全运营专题')
  })
})
