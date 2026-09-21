import { afterEach, describe, expect, it, vi } from 'vitest'
import { resourceApi } from './api'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('课程资源接口课程上下文', () => {
  it('所有请求均在调用时使用当前选择课程的地址、请求体和请求头', async () => {
    const courseId = 'course selected/42'
    localStorage.setItem('yk-course-id', courseId)
    vi.stubGlobal('crypto', { subtle: { digest: vi.fn(async () => new Uint8Array(32).fill(0xab).buffer) } } as unknown as Crypto)
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    const file = new File([new Uint8Array([80, 75, 3, 4])], 'content.xlsx')

    await resourceApi.blueprint()
    await resourceApi.resources()
    await resourceApi.readiness()
    await resourceApi.uploadFile(file)
    await resourceApi.createResource({ lesson_id: 'lesson-1', name: '第一课', resource_type: 'PPT' })
    await resourceApi.createVersion('resource-1', { file_id: 'file-1', sha256: 'a'.repeat(64) })
    await resourceApi.download('resource-1')
    await resourceApi.coverage()
    await resourceApi.questionImportTemplate()
    await resourceApi.importQuestions(file)
    await resourceApi.questionImportJob('job-1')
    await resourceApi.questionImportErrors('job-1')
    await resourceApi.questionReviewQueue()
    await resourceApi.reviewQuestion('question-1', 'APPROVED')
    await resourceApi.audit()
    await resourceApi.latestAudit()
    await resourceApi.manifest()
    await resourceApi.manifestXlsx()
    await resourceApi.freeze()

    const calls = fetchMock.mock.calls as [RequestInfo | URL, RequestInit][]
    expect(calls.every(([, init]) => new Headers(init.headers).get('X-Course-Ids') === courseId)).toBe(true)
    expect(calls.some(([url]) => String(url) === '/api/v1/resources/course-blueprint/course%20selected%2F42')).toBe(true)
    expect(calls.some(([url]) => String(url) === '/api/v1/resources?course_id=course%20selected%2F42')).toBe(true)
    expect(calls.some(([url]) => String(url) === '/api/v1/questions/review-queue?page_size=200&course_id=course%20selected%2F42')).toBe(true)
    expect(calls.some(([url]) => String(url) === '/api/v1/resources/delivery/manifest.xlsx?course_id=course%20selected%2F42')).toBe(true)

    const upload = calls.find(([url]) => String(url).endsWith('/resources/files'))
    expect((upload?.[1].body as FormData).get('course_id')).toBe(courseId)
    const questionImport = calls.find(([url]) => String(url).endsWith('/questions/import'))
    expect((questionImport?.[1].body as FormData).get('course_id')).toBe(courseId)
    const create = calls.find(([url, init]) => String(url) === '/api/v1/resources' && init.method === 'POST')
    expect(JSON.parse(String(create?.[1].body))).toMatchObject({ course_id: courseId, lesson_id: 'lesson-1' })
    for (const endpoint of ['/api/v1/resources/audit/run', '/api/v1/resources/delivery/freeze']) {
      const call = calls.find(([url]) => String(url) === endpoint)
      expect(JSON.parse(String(call?.[1].body))).toEqual({ course_id: courseId })
    }
  })

  it('切换课程后后续调用立即使用新课程，不保留模块加载时的旧值', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    localStorage.setItem('yk-course-id', 'course-a')
    await resourceApi.readiness()
    localStorage.setItem('yk-course-id', 'course-b')
    await resourceApi.readiness()

    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      '/api/v1/resources/readiness?course_id=course-a',
      '/api/v1/resources/readiness?course_id=course-b',
    ])
    expect(fetchMock.mock.calls.map(([, init]) => new Headers(init?.headers).get('X-Course-Ids'))).toEqual(['course-a', 'course-b'])
  })
})
