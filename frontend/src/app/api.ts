import type { components } from './api-contract.generated'

export type ApiError = components['schemas']['Error']
export type UserContext = components['schemas']['UserContextResponse']

export type LabSpec = components['schemas']['LabDefinitionSpec']
export type LabVersion = components['schemas']['LabVersionResponse']
export type Lab = components['schemas']['LabDefinitionResponse']
export type LabRelease = components['schemas']['LabReleaseResponse']

const devHeaders: HeadersInit = import.meta.env.DEV ? {
  'X-User-Id': 'user_teacher_demo', 'X-Role': 'teacher', 'X-Teacher-Id': 'teacher_demo',
  'X-Permissions': 'labs.read,labs.write,labs.publish,labs.knowledge.write,runtime.read,runtime.start,runtime.preview,runtime.destroy,runtime.rebuild,runtime.extend,runtime.rejudge,runtime.terminal,infrastructure.read,infrastructure.write',
  'X-Course-Ids': 'course_data_security,course_web_security', 'X-Class-Ids': 'class_netsec_2301',
} : {}

function idempotencyKey(action: string): string { return `${action}-${crypto.randomUUID()}` }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(devHeaders)
  new Headers(init.headers).forEach((value, key) => headers.set(key, value))
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) throw await response.json() as ApiError
  return response.json() as Promise<T>
}

export function getCurrentContext(): Promise<UserContext> {
  return api<UserContext>('/api/v1/auth/context')
}

const teacherPermissions = ['teaching.course.read','teaching.course.write','teaching.class.read','teaching.class.write','teaching.members.read','teaching.members.import','teaching.members.write','teaching.attendance.read','teaching.attendance.write','teaching.poll.read','teaching.poll.write','teaching.assignment.write','teaching.quiz.write','teaching.dashboard.read']

export function teachingIdentity(role = 'teacher'): Record<string, string> {
  if (!import.meta.env.DEV) return {}
  const courseId = localStorage.getItem('yk-course-id') || '', classId = localStorage.getItem('yk-class-id') || ''
  if (role === 'student') return {'X-User-Id':localStorage.getItem('yk-student-id')||'student-demo','X-Role':'student','X-Student-Id':localStorage.getItem('yk-student-id')||'student-demo','X-Permissions':'teaching.student.read,teaching.course.read,teaching.attendance.sign,teaching.poll.answer,teaching.assignment.submit,teaching.quiz.submit','X-Course-Ids':courseId,'X-Class-Ids':classId}
  return {'X-User-Id':'teacher-a','X-Role':'teacher','X-Teacher-Id':'teacher-a','X-Permissions':teacherPermissions.join(','),'X-Course-Ids':courseId || 'course_data_security,course_web_security','X-Class-Ids':classId}
}

export async function api<T>(path:string,init:RequestInit={},role?:'teacher'|'student'):Promise<T>{const response=await fetch(path,{...init,headers:{...teachingIdentity(role),...(init.body instanceof FormData?{}:{'Content-Type':'application/json'}),...(init.headers||{})}});if(!response.ok)throw await response.json() as ApiError;return response.json() as Promise<T>}
export async function download(path:string):Promise<Blob>{const response=await fetch(path,{headers:teachingIdentity()});if(!response.ok)throw await response.json() as ApiError;return response.blob()}
async function readBlobBytes(blob: Blob): Promise<ArrayBuffer> {
  if (typeof blob.arrayBuffer === 'function') return blob.arrayBuffer()
  return new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error ?? new Error('文件读取失败'))
    reader.onload = () => reader.result instanceof ArrayBuffer
      ? resolve(reader.result)
      : reject(new Error('文件读取结果无效'))
    reader.readAsArrayBuffer(blob)
  })
}
export async function fileIdempotencyKey(prefix:string,file:File):Promise<string>{const digest=await crypto.subtle.digest('SHA-256',await readBlobBytes(file));const hex=Array.from(new Uint8Array(digest),value=>value.toString(16).padStart(2,'0')).join('');return `${prefix}-${hex}`}

export type LessonResource = components['schemas']['ResourceLessonResponse']
export type ResourceVersion = components['schemas']['ResourceVersionResponse']
export type Resource = components['schemas']['ResourceResponse']
export type Audit = components['schemas']['ResourceAuditResponse']
export type ResourceReadiness = components['schemas']['ResourceReadinessResponse']
export type ResourceFile = components['schemas']['ResourceFileResponse']
export type ResourceManifest = Omit<components['schemas']['ResourceManifestResponse'], 'version_no'> & {
  version_no: number | null
}
export type QuestionRowError = components['schemas']['QuestionImportErrorResponse'] & { row_number: number | null }
export type QuestionImportJob = components['schemas']['QuestionImportJobResponse'] & { error_rows: QuestionRowError[] }
export type QuestionOption = components['schemas']['QuestionOptionResponse']
export type QuestionReviewItem = components['schemas']['QuestionReviewQueueItem'] & {
  answer: string[]; explanation: string; options: QuestionOption[]
}
export type QuestionReviewQueue = components['schemas']['QuestionReviewQueueResponse'] & { items: QuestionReviewItem[] }
export type PublishedCourseQuestionList = components['schemas']['QuestionListResponse']

const DEFAULT_RESOURCE_COURSE_ID = 'course_data_security'
export function selectedResourceCourseId(): string {
  const courseId = localStorage.getItem('yk-course-id')?.trim() || (import.meta.env.DEV ? DEFAULT_RESOURCE_COURSE_ID : '')
  if (!courseId) throw new Error('请先在课程总览选择课程')
  return courseId
}
function resourceIdentityHeaders(): Record<string, string> {
  if (import.meta.env.DEV) return {
    'X-User-Id': 'teacher_b',
    'X-Role': 'teacher',
    'X-Teacher-Id': 'teacher_b',
    'X-Course-Ids': selectedResourceCourseId(),
    'X-Permissions': 'resources:read,resources:write,resources:review,resources:freeze',
  }
  return {}
}
function resourceQuery(path: string): string {
  const separator = path.includes('?') ? '&' : '?'
  return `${path}${separator}course_id=${encodeURIComponent(selectedResourceCourseId())}`
}
export const resourceUserId = import.meta.env.DEV ? 'teacher_b' : ''
async function resourceRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(resourceIdentityHeaders())
  new Headers(init.headers).forEach((value, key) => headers.set(key, value))
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) throw await response.json() as ApiError
  return response.json() as Promise<T>
}
async function resourceDownload(path: string): Promise<Blob> {
  const response = await fetch(path, { headers: resourceIdentityHeaders() })
  if (!response.ok) throw await response.json() as ApiError
  return response.blob()
}
function normalizeResourceManifest(manifest: components['schemas']['ResourceManifestResponse']): ResourceManifest {
  return { ...manifest, version_no: manifest.version_no ?? null }
}
export const resourceApi = {
  blueprint: () => resourceRequest<components['schemas']['ResourceBlueprintResponse']>(`/api/v1/resources/course-blueprint/${encodeURIComponent(selectedResourceCourseId())}`),
  resources: () => resourceRequest<components['schemas']['ResourceListResponse']>(resourceQuery('/api/v1/resources')),
  publishedQuestions: () => resourceRequest<PublishedCourseQuestionList>(resourceQuery('/api/v1/questions?status=PUBLISHED')),
  readiness: () => resourceRequest<ResourceReadiness>(resourceQuery('/api/v1/resources/readiness')),
  uploadFile: (file: File) => { const body = new FormData(); body.append('course_id', selectedResourceCourseId()); body.append('file', file); return resourceRequest<ResourceFile>('/api/v1/resources/files', { method: 'POST', body }) },
  createResource: (data: { lesson_id: string; name: string; resource_type: string }) => resourceRequest<Resource>('/api/v1/resources', { method: 'POST', body: JSON.stringify({ course_id: selectedResourceCourseId(), ...data }) }),
  createVersion: (resourceId: string, data: { file_id: string; sha256: string; lab_file_count?: number }) => resourceRequest<ResourceVersion>(`/api/v1/resources/${resourceId}/versions`, { method: 'POST', body: JSON.stringify(data) }),
  download: (resourceId: string) => resourceDownload(`/api/v1/resources/${resourceId}/download`),
  coverage: () => resourceRequest<components['schemas']['QuestionCoverageResponse']>(resourceQuery('/api/v1/questions/coverage')),
  questionImportTemplate: () => resourceDownload(resourceQuery('/api/v1/questions/import-template.xlsx')),
  importQuestions: async (file: File) => {
    const body = new FormData(); body.append('course_id', selectedResourceCourseId()); body.append('file', file)
    const idempotencyKey = await fileIdempotencyKey('questions', file)
    return resourceRequest<QuestionImportJob>('/api/v1/questions/import', { method: 'POST', body, headers: { 'Idempotency-Key': idempotencyKey } })
  },
  questionImportJob: (jobId: string) => resourceRequest<QuestionImportJob>(`/api/v1/questions/import-jobs/${jobId}`),
  questionImportErrors: (jobId: string) => resourceDownload(`/api/v1/questions/import-jobs/${jobId}/error-rows.xlsx`),
  questionReviewQueue: () => resourceRequest<QuestionReviewQueue>(resourceQuery('/api/v1/questions/review-queue?page_size=200')),
  reviewQuestion: (questionId: string, decision: 'APPROVED' | 'REJECTED', comment?: string) => resourceRequest<components['schemas']['QuestionStatusResponse']>(`/api/v1/questions/${questionId}/review`, { method: 'POST', body: JSON.stringify({ decision, comment: comment?.trim() || null }) }),
  audit: () => resourceRequest<Audit>('/api/v1/resources/audit/run', { method: 'POST', body: JSON.stringify({ course_id: selectedResourceCourseId() }) }),
  latestAudit: () => resourceRequest<Audit>(resourceQuery('/api/v1/resources/audit/latest')),
  manifest: async () => normalizeResourceManifest(await resourceRequest<components['schemas']['ResourceManifestResponse']>(resourceQuery('/api/v1/resources/delivery/manifest.json'))),
  manifestXlsx: () => resourceDownload(resourceQuery('/api/v1/resources/delivery/manifest.xlsx')),
  freeze: async () => normalizeResourceManifest(await resourceRequest<components['schemas']['ResourceManifestResponse']>('/api/v1/resources/delivery/freeze', { method: 'POST', body: JSON.stringify({ course_id: selectedResourceCourseId() }) })),
}

export async function listLabs(): Promise<Lab[]> { return (await request<components['schemas']['LabDefinitionListResponse']>('/api/v1/labs')).items }
export async function importLab(file: File, metadata: { course_id: string; code: string; category: string; objective: string }): Promise<Lab> {
  const body = new FormData()
  body.append('file', file)
  for (const [key, value] of Object.entries(metadata)) body.append(key, value)
  const key = await fileIdempotencyKey(`lab-import-${metadata.course_id}-${metadata.code}`, file)
  return request<Lab>('/api/v1/labs/import', { method: 'POST', headers: { 'X-Idempotency-Key': key }, body })
}
export async function listTemplates(): Promise<components['schemas']['LabTemplateResponse'][]> { return (await request<components['schemas']['LabTemplateListResponse']>('/api/v1/lab-templates')).items }
export async function listKnowledge(): Promise<components['schemas']['LabKnowledgeResponse'][]> { return (await request<components['schemas']['LabKnowledgeListResponse']>('/api/v1/lab-knowledge')).items }
export async function downloadKnowledgeDiagram(knowledgeId: string, diagramId: string): Promise<Blob> {
  const response = await fetch(`/api/v1/lab-knowledge/${knowledgeId}/diagrams/${diagramId}/download`, { headers: new Headers(devHeaders) })
  if (!response.ok) throw await response.json() as ApiError
  return response.blob()
}
export async function cloneVersion(labId: string): Promise<LabVersion> { return request(`/api/v1/labs/${labId}/versions`, { method: 'POST', headers: { 'X-Idempotency-Key': idempotencyKey('clone') }, body: '{}' }) }
export async function saveVersion(version: LabVersion): Promise<LabVersion> { return request(`/api/v1/lab-versions/${version.lab_version_id}`, { method: 'PATCH', headers: { 'X-Idempotency-Key': idempotencyKey('save') }, body: JSON.stringify({ spec: version.spec }) }) }
export async function validateVersion(versionId: string): Promise<LabVersion> { return request(`/api/v1/lab-versions/${versionId}/validate`, { method: 'POST', headers: { 'X-Idempotency-Key': idempotencyKey('validate') } }) }
export async function publishVersion(versionId: string): Promise<LabVersion> { return request(`/api/v1/lab-versions/${versionId}/publish`, { method: 'POST', headers: { 'X-Idempotency-Key': idempotencyKey('publish') } }) }
export async function exportVersion(versionId: string): Promise<Blob> {
  const headers = new Headers(devHeaders)
  const response = await fetch(`/api/v1/lab-versions/${versionId}/export.json`, { headers })
  if (!response.ok) throw await response.json() as ApiError
  return response.blob()
}
export async function createRelease(versionId: string, scope: { course_id: string; class_id: string; lesson_id: string; max_concurrency: number }): Promise<LabRelease> {
  const opensAt = new Date(Date.now() + 60_000)
  const closesAt = new Date(opensAt.getTime() + 60 * 60_000)
  return request('/api/v1/lab-releases', { method: 'POST', headers: { 'X-Idempotency-Key': idempotencyKey('release') }, body: JSON.stringify({ lab_version_id: versionId, ...scope, opens_at: opensAt.toISOString(), closes_at: closesAt.toISOString(), max_attempts: 3, timeout_minutes: 60, teacher_preview_required: true }) })
}
export async function preflightRelease(releaseId: string): Promise<components['schemas']['LabReleasePreflightResponse']> { return request(`/api/v1/lab-releases/${releaseId}/preflight`, { method: 'POST', headers: { 'X-Idempotency-Key': idempotencyKey('preflight') } }) }
export async function teacherPreview(releaseId: string): Promise<components['schemas']['LabTeacherPreviewResponse']> { return request(`/api/v1/lab-releases/${releaseId}/teacher-preview`, { method: 'POST', headers: { 'X-Idempotency-Key': idempotencyKey('preview') } }) }
export async function publishRelease(releaseId: string): Promise<LabRelease> { return request(`/api/v1/lab-releases/${releaseId}/publish`, { method: 'POST', headers: { 'X-Idempotency-Key': idempotencyKey('release-publish') } }) }

export type RuntimeNode = components['schemas']['RuntimeNodeResponse']
export type RuntimeImage = components['schemas']['RuntimeImageResponse']
export type RuntimeInstanceSummary = components['schemas']['RuntimeInstanceSummaryResponse']
export type RuntimeQueueItem = components['schemas']['RuntimeQueueItemResponse']
export type RuntimeEvent = components['schemas']['RuntimeEventResponse']
export type RuntimeOverview = components['schemas']['RuntimeOverviewResponse']

export async function runtimeOverview(): Promise<RuntimeOverview> { return request('/api/v1/infrastructure/overview') }
export async function runtimeNodes(): Promise<RuntimeNode[]> { return (await request<components['schemas']['RuntimeNodeListResponse']>('/api/v1/infrastructure/nodes')).items }
export async function runtimeImages(): Promise<RuntimeImage[]> { return (await request<components['schemas']['RuntimeImageListResponse']>('/api/v1/infrastructure/images')).items }
export async function runtimeInstances(): Promise<RuntimeInstanceSummary[]> { return (await request<components['schemas']['RuntimeInstanceListResponse']>('/api/v1/runtime-instances')).items }
export async function runtimeQueue(): Promise<RuntimeQueueItem[]> { return (await request<components['schemas']['RuntimeQueueListResponse']>('/api/v1/infrastructure/queue')).items }
export async function runtimeEvents(): Promise<RuntimeEvent[]> { return (await request<components['schemas']['RuntimeEventListResponse']>('/api/v1/infrastructure/events')).items }

const classroomTeacherPermissions = [
  'classroom.release.read','classroom.runtime.remind','classroom.runtime.rejudge','classroom.runtime.extend',
  'classroom.runtime.unlock','classroom.runtime.rebuild','classroom.runtime.destroy','classroom.release.extend-all',
  'classroom.release.remind-idle','classroom.terminal.assist','classroom.logs.read','classroom.logs.download',
  'classroom.logs.distribute','classroom.readmodel.read'
]
const classroomStudentPermissions = ['classroom.lab.start','classroom.lab.read','classroom.lab.submit','classroom.terminal.use','classroom.logs.assignment.read','classroom.logs.assignment.download']

export function classroomHeaders(role: 'teacher' | 'student', extra: HeadersInit = {}): HeadersInit {
  if (!import.meta.env.DEV) return {
    'Content-Type': 'application/json',
    ...extra,
  }
  const studentId = localStorage.getItem('yk-student-id') || 'student-a'
  return {
    'Content-Type': 'application/json',
    'X-User-Id': role === 'teacher' ? 'teacher-user' : `user-${studentId}`,
    'X-Role': role,
    'X-Teacher-Id': role === 'teacher' ? 'teacher-a' : '',
    'X-Student-Id': role === 'student' ? studentId : '',
    'X-Permissions': (role === 'teacher' ? classroomTeacherPermissions : classroomStudentPermissions).join(','),
    'X-Course-Ids': localStorage.getItem('yk-course-id') || 'course-a',
    'X-Class-Ids': localStorage.getItem('yk-class-id') || 'class-a',
    ...extra,
  }
}

export async function classroomApi<T>(path: string, role: 'teacher' | 'student' = 'teacher', init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...init, headers: classroomHeaders(role, init.headers) })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ code: 'NETWORK.ERROR', message: '服务暂不可用', request_id: '', details: {} }))
    throw error as ApiError
  }
  return response.json() as Promise<T>
}

export async function classroomDownload(path: string, role: 'teacher' | 'student' = 'teacher'): Promise<Blob> {
  const response = await fetch(path, { headers: classroomHeaders(role) })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ code: 'NETWORK.ERROR', message: '文件下载失败', request_id: '', details: {} }))
    throw error as ApiError
  }
  return response.blob()
}

export function subscribeClassroomEvents(
  releaseId: string,
  onEvent: (event: unknown) => void,
  onError?: (message: string) => void,
): () => void {
  const controller = new AbortController()
  let cursor = 0
  const pause = (milliseconds: number) => new Promise(resolve => setTimeout(resolve, milliseconds))
  void (async () => {
    while (!controller.signal.aborted) {
      try {
        const response = await fetch(`/api/v1/classroom/lab-releases/${encodeURIComponent(releaseId)}/events?cursor=${cursor}`, {
          headers: classroomHeaders('teacher', { Accept: 'text/event-stream' }),
          signal: controller.signal,
        })
        if (!response.ok || !response.body) throw new Error('课堂实时连接不可用')
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
          let boundary = buffer.indexOf('\n\n')
          while (boundary >= 0) {
            const block = buffer.slice(0, boundary)
            buffer = buffer.slice(boundary + 2)
            const id = block.split('\n').find(line => line.startsWith('id:'))?.slice(3).trim()
            const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n')
            if (id && Number.isFinite(Number(id))) cursor = Number(id)
            if (data) onEvent(JSON.parse(data))
            boundary = buffer.indexOf('\n\n')
          }
        }
      } catch (reason) {
        if (controller.signal.aborted) return
        onError?.((reason as Error).message || '课堂实时连接已断开')
      }
      if (!controller.signal.aborted) await pause(1000)
    }
  })()
  return () => controller.abort()
}

function gradingScope() {
  return {
    courseId: localStorage.getItem('yk-course-id') || 'course_data_security',
    classId: localStorage.getItem('yk-class-id') || 'class_netsec_2301',
    lessonId: localStorage.getItem('yk-lesson-id') || 'lesson_3_2',
    studentId: localStorage.getItem('yk-student-id') || 'student_1',
  }
}

function gradingIdentity(role: 'teacher' | 'student' | 'admin'): Record<string, string> {
  if (!import.meta.env.DEV) return {}
  const scope = gradingScope()
  if (role === 'student') return { 'X-User-Id': `user_${scope.studentId}`, 'X-Role': 'student', 'X-Student-Id': scope.studentId, 'X-Course-Ids': scope.courseId, 'X-Class-Ids': scope.classId, 'X-Permissions': 'grading:read,analytics:read' }
  if (role === 'admin') return { 'X-User-Id': 'admin_f', 'X-Role': 'admin', 'X-Permissions': 'audit:read,grading:all-courses,grading:all-classes' }
  return { 'X-User-Id': 'teacher_f', 'X-Role': 'teacher', 'X-Teacher-Id': 'teacher_f', 'X-Course-Ids': scope.courseId, 'X-Class-Ids': scope.classId, 'X-Permissions': 'grading:read,grading:policy,grading:recalculate,grading:post,analytics:class,analytics:read,archives:read,archives:write,archives:freeze' }
}

async function gradingRequest<T>(path:string, init:RequestInit={}, role:'teacher'|'student'|'admin'='teacher'):Promise<T>{
  const identity = gradingIdentity(role)
  const response=await fetch(path,{...init,headers:{...identity,'Content-Type':'application/json',...(init.headers||{})}})
  if(!response.ok)throw await response.json() as ApiError
  return response.json() as Promise<T>
}
async function gradingDownload(path:string,role:'teacher'|'admin'='teacher'):Promise<Blob>{
  const response=await fetch(path,{headers:gradingIdentity(role)})
  if(!response.ok)throw await response.json() as ApiError
  return response.blob()
}
export const gradingApi={
  policy:()=>{ const { courseId } = gradingScope(); return gradingRequest<components['schemas']['GradingPolicyResponse']>(`/api/v1/grading/policies/${courseId}`) },
  gradebook:()=>{ const { courseId, classId } = gradingScope(); return gradingRequest<components['schemas']['GradebookResponse']>(`/api/v1/gradebook/courses/${courseId}?class_id=${classId}`) },
  trace:(studentId:string)=>{ const { courseId, classId } = gradingScope(); return gradingRequest<components['schemas']['GradebookTraceResponse']>(`/api/v1/gradebook/courses/${courseId}/trace/${studentId}?class_id=${classId}`) },
  recalculate:()=>{ const { courseId, classId } = gradingScope(); return gradingRequest<components['schemas']['GradebookResponse']>(`/api/v1/grading/courses/${courseId}/recalculate`,{method:'POST',body:JSON.stringify({class_id:classId})}) },
  post:()=>{ const { courseId, classId } = gradingScope(); return gradingRequest<components['schemas']['GradebookResponse']>(`/api/v1/grading/courses/${courseId}/post?class_id=${classId}`,{method:'POST'}) },
  overview:()=>{ const { courseId, classId } = gradingScope(); return gradingRequest<components['schemas']['AnalyticsOverviewResponse']>(`/api/v1/analytics/courses/${courseId}/overview?class_id=${classId}`) },
  section:(lessonId?:string)=>{ const scope = gradingScope(); return gradingRequest<components['schemas']['AnalyticsSectionResponse']>(`/api/v1/analytics/courses/${scope.courseId}/sections/${lessonId || scope.lessonId}?class_id=${scope.classId}`) },
  labsStudent:()=>{ const { courseId, classId } = gradingScope(); return gradingRequest<components['schemas']['AnalyticsStudentLabListResponse']>(`/api/v1/analytics/courses/${courseId}/labs/by-student?class_id=${classId}`) },
  labsLab:()=>{ const { courseId, classId } = gradingScope(); return gradingRequest<components['schemas']['AnalyticsLabListResponse']>(`/api/v1/analytics/courses/${courseId}/labs/by-lab?class_id=${classId}`) },
  risks:()=>{ const { courseId, classId } = gradingScope(); return gradingRequest<components['schemas']['StudentRiskListResponse']>(`/api/v1/analytics/courses/${courseId}/risks?class_id=${classId}`) },
  precheck:()=>{ const { courseId, classId } = gradingScope(); return gradingRequest<components['schemas']['ArchivePrecheckResponse']>(`/api/v1/archives/courses/${courseId}/precheck`,{method:'POST',body:JSON.stringify({class_id:classId})}) },
  freeze:()=>{ const { courseId, classId } = gradingScope(); return gradingRequest<components['schemas']['ArchiveManifestPayloadResponse']>(`/api/v1/archives/courses/${courseId}/freeze`,{method:'POST',body:JSON.stringify({class_id:classId})}) },
  archive:()=>{ const { courseId, classId } = gradingScope(); return gradingRequest<components['schemas']['ArchiveResponse']>(`/api/v1/archives/courses/${courseId}?class_id=${classId}`) },
  gradebookExport:()=>{ const { courseId, classId } = gradingScope(); return gradingDownload(`/api/v1/gradebook/courses/${courseId}/export.xlsx?class_id=${classId}`) },
  analyticsExport:()=>{ const { courseId, classId } = gradingScope(); return gradingDownload(`/api/v1/analytics/courses/${courseId}/export.xlsx?class_id=${classId}`) },
  archiveArtifact:(artifactType:string)=>{ const { courseId, classId } = gradingScope(); return gradingDownload(`/api/v1/archives/courses/${courseId}/artifacts/${encodeURIComponent(artifactType)}?class_id=${classId}`) },
  studentScore:()=>{ const { courseId, classId, studentId } = gradingScope(); return gradingRequest<components['schemas']['LearningSummaryResponse']>(`/api/v1/analytics/courses/${courseId}/learning-summary?class_id=${classId}&student_id=${studentId}`,{},'student') },
  audit:()=>gradingRequest<components['schemas']['AuditEventListResponse']>('/api/v1/audit/events',{},'admin'),
  auditExport:(format:'xlsx'|'csv')=>gradingDownload(`/api/v1/audit/events/export.${format}`,'admin'),
}


export type ContentPackSummary = {
  pack_id: string; course_id: string; title: string; version: string; language: string;
  content_origin: string; commercial_bundle_allowed: boolean; theory_lessons: number; lab_lessons: number
}
export type ContentSource = { name: string; url: string; license_id: string; use_mode: string; license_decision: string; license_reason: string }
export type WebLabCandidate = { lesson_code: string; lab_definition_id: string; title: string; source: string; license: string; source_path: string | null; runtime_status: string; reason: string }

function contentPackHeaders(): Record<string,string> {
  if (!import.meta.env.DEV) return {}
  return {
    ...teachingIdentity('teacher'),
    'X-Permissions': [...teacherPermissions, 'resources:read', 'labs.read'].join(','),
    'X-Course-Ids': localStorage.getItem('yk-course-id') || 'course_data_security,course_web_security',
  }
}
async function contentPackRequest<T>(path:string, init:RequestInit={}):Promise<T>{
  const response=await fetch(path,{...init,headers:{...contentPackHeaders(),...(init.headers||{})}})
  if(!response.ok)throw await response.json() as ApiError
  return response.json() as Promise<T>
}
export const contentPackApi={
  list:()=>contentPackRequest<{items:ContentPackSummary[]}>('/api/v1/content-packs'),
  sources:()=>contentPackRequest<{items:ContentSource[]}>('/api/v1/content-sources'),
  webLabCandidates:()=>contentPackRequest<{labs:WebLabCandidate[]}>('/api/v1/content-packs/web_security_v1/lab-candidates'),
  seedDomainMap:()=>contentPackRequest<{domain_map:{source_category:string;yueke_course:string;status:string}[]}>('/api/v1/content-source-maps/seed'),
  previewVulhub:(file:File)=>{const body=new FormData();body.append('file',file);return contentPackRequest<{items:unknown[];total:number}>('/api/v1/content-sources/vulhub/index/preview',{method:'POST',body})},
  scanCompose:(file:File)=>{const body=new FormData();body.append('file',file);return contentPackRequest<{passed:boolean;findings:{code:string;message:string;service?:string;blocking:boolean}[]}>('/api/v1/content-sources/compose/scan',{method:'POST',body})},
  previewAtomic:(file:File)=>{const body=new FormData();body.append('file',file);return contentPackRequest<{attack_technique:string;display_name:string;test_count:number;execution_imported:boolean}>('/api/v1/content-sources/atomic-red-team/preview',{method:'POST',body})},
  previewDojo:(file:File)=>{const body=new FormData();body.append('file',file);return contentPackRequest<{dojo_id:string;name:string;module_count:number;content_imported:boolean}>('/api/v1/content-sources/pwncollege/dojo/preview',{method:'POST',body})},
}

export type ChallengeItem = {
  challenge_id:string;course_id:string;lesson_id:string;lab_definition_id:string|null;lab_version_id:string|null;checkpoint_key:string|null;
  prerequisite_challenge_id:string|null;unlocked:boolean;
  title:string;description:string;difficulty:string;max_attempts:number;status:string;flag_configured:boolean
}
function challengeHeaders(role:'teacher'|'student'):Record<string,string>{
  if(!import.meta.env.DEV)return {}
  const base=teachingIdentity(role)
  return {
    ...base,
    'X-Permissions': role==='teacher' ? 'labs.read,labs.write,teaching.course.read' : 'classroom.lab.read,classroom.lab.start',
    'X-Course-Ids': localStorage.getItem('yk-course-id') || 'course_web_security',
    'X-Class-Ids': localStorage.getItem('yk-class-id') || '',
  }
}
async function challengeRequest<T>(path:string,role:'teacher'|'student',init:RequestInit={}):Promise<T>{
  const response=await fetch(path,{...init,headers:{...challengeHeaders(role),'Content-Type':'application/json',...(init.headers||{})}})
  if(!response.ok)throw await response.json() as ApiError
  return response.json() as Promise<T>
}
export const challengeApi={
  list:(courseId:string,role:'teacher'|'student')=>challengeRequest<{items:ChallengeItem[];total:number}>(`/api/v1/challenges?course_id=${encodeURIComponent(courseId)}`,role),
  hints:(id:string,role:'teacher'|'student')=>challengeRequest<{items:{hint_id:string;title:string;content:string;unlock_after_attempts:number}[];attempts:number;total:number}>(`/api/v1/challenges/${id}/hints`,role),
  configureFlag:(id:string,flag:string)=>challengeRequest(`/api/v1/challenges/${id}/flag`,'teacher',{method:'PUT',body:JSON.stringify({flag,case_sensitive:true})}),
  submit:(id:string,submission:string,classId:string,releaseId:string,runtimeInstanceId:string)=>challengeRequest<{attempt_id:string;runtime_instance_id:string|null;checkpoint_result_id:string|null;accepted:boolean;remaining_attempts:number}>(`/api/v1/challenges/${id}/submit`,'student',{method:'POST',body:JSON.stringify({submission,class_id:classId,lab_release_id:releaseId,runtime_instance_id:runtimeInstanceId})}),
}
