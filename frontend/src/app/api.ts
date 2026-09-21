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
