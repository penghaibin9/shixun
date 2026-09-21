export type ApiError = { code: string; message: string; request_id: string; details: Record<string, unknown> }
export type UserContext = { user_id: string; role: 'teacher' | 'student' | 'admin'; teacher_id: string | null; student_id: string | null; permissions: string[]; course_ids: string[]; class_ids: string[] }

export async function getCurrentContext(headers: HeadersInit = {}): Promise<UserContext> {
  const response = await fetch('/api/v1/auth/context', { headers })
  if (!response.ok) throw await response.json() as ApiError
  return response.json() as Promise<UserContext>
}

const courseId = 'course_data_security', classId = 'class_2301'
const teacherHeaders = { 'X-User-Id':'teacher_f','X-Role':'teacher','X-Teacher-Id':'teacher_f','X-Course-Ids':courseId,'X-Class-Ids':classId,'X-Permissions':'grading:manage,audit:read' }
const studentHeaders = { 'X-User-Id':'user_s1','X-Role':'student','X-Student-Id':'student_1','X-Course-Ids':courseId,'X-Class-Ids':classId,'X-Permissions':'grading:read,analytics:read' }
const adminHeaders = { 'X-User-Id':'admin_f','X-Role':'admin','X-Permissions':'audit:read,grading:all-courses,grading:all-classes' }
async function api<T>(path:string, init:RequestInit={}, role:'teacher'|'student'|'admin'='teacher'):Promise<T>{
  const identity=role==='student'?studentHeaders:role==='admin'?adminHeaders:teacherHeaders
  const response=await fetch(path,{...init,headers:{...identity,'Content-Type':'application/json',...(init.headers||{})}})
  if(!response.ok)throw await response.json() as ApiError
  return response.json() as Promise<T>
}
export const gradingApi={
  policy:()=>api<any>(`/api/v1/grading/policies/${courseId}`),
  gradebook:()=>api<any>(`/api/v1/gradebook/courses/${courseId}`),
  trace:(studentId:string)=>api<any>(`/api/v1/gradebook/courses/${courseId}/trace/${studentId}`),
  recalculate:()=>api<any>(`/api/v1/grading/courses/${courseId}/recalculate`,{method:'POST',body:JSON.stringify({class_id:classId})}),
  post:()=>api<any>(`/api/v1/grading/courses/${courseId}/post`,{method:'POST'}),
  overview:()=>api<any>(`/api/v1/analytics/courses/${courseId}/overview`),
  section:(lessonId='lesson_3_2')=>api<any>(`/api/v1/analytics/courses/${courseId}/sections/${lessonId}`),
  labsStudent:()=>api<any>(`/api/v1/analytics/courses/${courseId}/labs/by-student`),
  labsLab:()=>api<any>(`/api/v1/analytics/courses/${courseId}/labs/by-lab`),
  risks:()=>api<any>(`/api/v1/analytics/courses/${courseId}/risks`),
  precheck:()=>api<any>(`/api/v1/archives/courses/${courseId}/precheck`,{method:'POST',body:JSON.stringify({class_id:classId})}),
  freeze:()=>api<any>(`/api/v1/archives/courses/${courseId}/freeze`,{method:'POST',body:JSON.stringify({class_id:classId})}),
  archive:()=>api<any>(`/api/v1/archives/courses/${courseId}?class_id=${classId}`),
  studentScore:()=>api<any>(`/api/v1/analytics/courses/${courseId}/learning-summary?student_id=student_1`,{},'student'),
  audit:()=>api<any>('/api/v1/audit/events',{},'admin'),
}
