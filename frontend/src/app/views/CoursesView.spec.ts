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
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      items: [
        { course_id: 'course-a', name: '数据安全基础', term: '2026 秋季', status: 'ACTIVE', theory_lesson_count: 37, lab_lesson_count: 12 },
        { course_id: 'course-b', name: '安全运营专题', term: '2027 春季', status: 'DRAFT', theory_lesson_count: 18, lab_lesson_count: 7 },
      ],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    const wrapper = mount(CoursesView)
    await flushPromises()
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
