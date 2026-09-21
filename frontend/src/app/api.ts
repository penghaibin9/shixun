export type ApiError = { code: string; message: string; request_id: string; details: Record<string, unknown> }
export type UserContext = { user_id: string; role: 'teacher' | 'student' | 'admin'; teacher_id: string | null; student_id: string | null; permissions: string[]; course_ids: string[]; class_ids: string[] }

export type LabSpec = {
  lab_definition_id: string; version: number; name: string; duration_minutes: number; total_score: number
  nodes: Array<{ node_key: string; display_name: string; role: string; network_env: string; network_keys: string[]; device_model: string; image_id: string; image_digest: string; cpu_limit: number; memory_mb: number; ip_policy: string; ports: number[]; startup_command: string; mounts: string[]; position_x: number; position_y: number }>
  networks: Array<{ network_key: string; cidr_policy: string; internet_access: boolean; egress_allowlist: string[]; student_isolation: boolean }>
  image_bindings: Array<{ node_key: string; infra_image_id: string; digest: string }>
  steps: Array<{ node_key: string; name: string; description: string; order_no: number }>
  edges: Array<{ from_node_key: string; to_node_key: string }>
  checkpoints: Array<{ checkpoint_id: string; dag_node_id: string; name: string; score: number; judge_type: string; judge_target: string; judge_config_json: Record<string, unknown>; failure_message: string; timeout_seconds: number; order_no: number }>
  runtime_policy: { max_attempts: number; timeout_minutes: number }
}
export type LabVersion = { lab_version_id: string; lab_definition_id: string; version: number; status: string; spec: LabSpec; validation_errors: Array<{ code: string; message: string }>; published_at: string | null }
export type Lab = { lab_definition_id: string; course_id: string; code: string; name: string; category: string; objective: string; latest_version: LabVersion }
export type LabRelease = { lab_release_id: string; lab_version_id: string; course_id: string; class_id: string; status: string; publish_config: { preflight: Record<string, unknown>; preview_request_id: string | null } }

const devHeaders: HeadersInit = import.meta.env.DEV ? {
  'X-User-Id': 'user_teacher_demo', 'X-Role': 'teacher', 'X-Teacher-Id': 'teacher_demo',
  'X-Permissions': 'labs.read,labs.write,labs.publish,labs.knowledge.write',
  'X-Course-Ids': 'course_data_security', 'X-Class-Ids': 'class_netsec_2301',
} : {}

function idempotencyKey(action: string): string { return `${action}-${crypto.randomUUID()}` }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(devHeaders)
  new Headers(init.headers).forEach((value, key) => headers.set(key, value))
  if (init.body) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) throw await response.json() as ApiError
  return response.json() as Promise<T>
}

export async function getCurrentContext(headers: HeadersInit = {}): Promise<UserContext> {
  const response = await fetch('/api/v1/auth/context', { headers })
  if (!response.ok) throw await response.json() as ApiError
  return response.json() as Promise<UserContext>
}

export async function listLabs(): Promise<Lab[]> { return (await request<{ items: Lab[] }>('/api/v1/labs')).items }
export async function listTemplates(): Promise<Array<{ template_id: string; name: string; description: string; spec: Record<string, unknown> }>> { return (await request<{ items: Array<{ template_id: string; name: string; description: string; spec: Record<string, unknown> }> }>('/api/v1/lab-templates')).items }
export async function listKnowledge(): Promise<Array<{ knowledge_point_id: string; title: string; explain_text: string; question_ids: string[]; diagrams: Array<{ diagram_id: string; file_id: string; title: string }> }>> { return (await request<{ items: Array<{ knowledge_point_id: string; title: string; explain_text: string; question_ids: string[]; diagrams: Array<{ diagram_id: string; file_id: string; title: string }> }> }>('/api/v1/lab-knowledge')).items }
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
export async function createRelease(versionId: string): Promise<LabRelease> {
  const opensAt = new Date(Date.now() + 60_000)
  const closesAt = new Date(opensAt.getTime() + 60 * 60_000)
  return request('/api/v1/lab-releases', { method: 'POST', headers: { 'X-Idempotency-Key': idempotencyKey('release') }, body: JSON.stringify({ lab_version_id: versionId, course_id: 'course_data_security', class_id: 'class_netsec_2301', lesson_id: 'lesson_03_04', opens_at: opensAt.toISOString(), closes_at: closesAt.toISOString(), max_attempts: 3, timeout_minutes: 60, max_concurrency: 43, teacher_preview_required: true }) })
}
export async function preflightRelease(releaseId: string): Promise<{ passed: boolean; checks: Record<string, boolean> }> { return request(`/api/v1/lab-releases/${releaseId}/preflight`, { method: 'POST', headers: { 'X-Idempotency-Key': idempotencyKey('preflight') } }) }
export async function teacherPreview(releaseId: string): Promise<{ status: string; runtime_request_id: string }> { return request(`/api/v1/lab-releases/${releaseId}/teacher-preview`, { method: 'POST', headers: { 'X-Idempotency-Key': idempotencyKey('preview') } }) }
