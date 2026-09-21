export type ApiError = { code: string; message: string; request_id: string; details: Record<string, unknown> }
export type UserContext = { user_id: string; role: 'teacher' | 'student' | 'admin'; teacher_id: string | null; student_id: string | null; permissions: string[]; course_ids: string[]; class_ids: string[] }

export async function getCurrentContext(headers: HeadersInit = {}): Promise<UserContext> {
  const response = await fetch('/api/v1/auth/context', { headers })
  if (!response.ok) throw await response.json() as ApiError
  return response.json() as Promise<UserContext>
}

const teacherPermissions = ['teaching.course.read','teaching.course.write','teaching.class.read','teaching.class.write','teaching.members.read','teaching.members.import','teaching.members.write','teaching.attendance.read','teaching.attendance.write','teaching.poll.read','teaching.poll.write','teaching.assignment.write','teaching.quiz.write','teaching.dashboard.read']

export function teachingIdentity(role = 'teacher'): Record<string, string> {
  const courseId = localStorage.getItem('yk-course-id') || '', classId = localStorage.getItem('yk-class-id') || ''
  if (role === 'student') return {'X-User-Id':localStorage.getItem('yk-student-id')||'student-demo','X-Role':'student','X-Student-Id':localStorage.getItem('yk-student-id')||'student-demo','X-Permissions':'teaching.student.read,teaching.course.read,teaching.attendance.sign,teaching.poll.answer,teaching.assignment.submit,teaching.quiz.submit','X-Course-Ids':courseId,'X-Class-Ids':classId}
  return {'X-User-Id':'teacher-a','X-Role':'teacher','X-Teacher-Id':'teacher-a','X-Permissions':teacherPermissions.join(','),'X-Course-Ids':courseId,'X-Class-Ids':classId}
}

export async function api<T>(path:string,init:RequestInit={},role?:'teacher'|'student'):Promise<T>{const response=await fetch(path,{...init,headers:{...teachingIdentity(role),...(init.body instanceof FormData?{}:{'Content-Type':'application/json'}),...(init.headers||{})}});if(!response.ok)throw await response.json() as ApiError;return response.json() as Promise<T>}
export async function download(path:string):Promise<Blob>{const response=await fetch(path,{headers:teachingIdentity()});if(!response.ok)throw await response.json() as ApiError;return response.blob()}

export type LessonResource = { course_id: string; lesson_id: string; lesson_kind: 'THEORY' | 'LAB'; chapter_no: number | null; lesson_code: string; title: string; purpose: string | null; environment: string | null; principle: string | null; steps_summary: string | null; core_experiment: string | null }
export type Resource = { resource_id: string; course_id: string; lesson_id: string | null; name: string; resource_type: string; status: string; created_at: string }
export type Audit = { course_id: string; total: number; pass: number; warning: number; blocking: number; blocking_items: string[]; procurement_mapping: { requirement: string; owner: string; evidence: string }[] }

const identityHeaders = { 'X-User-Id': 'teacher_b', 'X-Role': 'teacher', 'X-Teacher-Id': 'teacher_b', 'X-Course-Ids': 'course_data_security', 'X-Permissions': 'resources:read,resources:write,resources:review,resources:freeze' }
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...init, headers: { ...identityHeaders, 'Content-Type': 'application/json', ...(init.headers || {}) } })
  if (!response.ok) throw await response.json() as ApiError
  return response.json() as Promise<T>
}
export const resourceApi = {
  blueprint: () => request<{ items: LessonResource[]; total: number; chapter_counts: Record<string, number> }>('/api/v1/resources/course-blueprint/course_data_security'),
  resources: () => request<{ items: Resource[]; total: number }>('/api/v1/resources?course_id=course_data_security'),
  coverage: () => request<{ items: { lesson_id: string; lesson_code: string; types: string[]; passed: boolean }[]; total: number; passed: number }>('/api/v1/questions/coverage'),
  audit: () => request<Audit>('/api/v1/resources/audit/run', { method: 'POST', body: JSON.stringify({ course_id: 'course_data_security' }) }),
  latestAudit: () => request<Audit>('/api/v1/resources/audit/latest'),
  manifest: () => request<{ status: string; version_no: number | null; theory_lessons: number; lab_lessons: number; audit: Audit; content_declaration: string }>('/api/v1/resources/delivery/manifest.json'),
  freeze: () => request('/api/v1/resources/delivery/freeze', { method: 'POST', body: JSON.stringify({ course_id: 'course_data_security' }) }),
}
