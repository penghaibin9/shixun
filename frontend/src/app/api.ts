export type ApiError = { code: string; message: string; request_id: string; details: Record<string, unknown> }
export type UserContext = { user_id: string; role: 'teacher' | 'student' | 'admin'; teacher_id: string | null; student_id: string | null; permissions: string[]; course_ids: string[]; class_ids: string[] }

export async function getCurrentContext(headers: HeadersInit = {}): Promise<UserContext> {
  const response = await fetch('/api/v1/auth/context', { headers })
  if (!response.ok) throw await response.json() as ApiError
  return response.json() as Promise<UserContext>
}

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
