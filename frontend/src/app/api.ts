export type ApiError = { code: string; message: string; request_id: string; details: Record<string, unknown> }
export type UserContext = { user_id: string; role: 'teacher' | 'student' | 'admin'; teacher_id: string | null; student_id: string | null; permissions: string[]; course_ids: string[]; class_ids: string[] }

export async function getCurrentContext(headers: HeadersInit = {}): Promise<UserContext> {
  const response = await fetch('/api/v1/auth/context', { headers })
  if (!response.ok) throw await response.json() as ApiError
  return response.json() as Promise<UserContext>
}

const teacherPermissions = [
  'classroom.release.read','classroom.runtime.remind','classroom.runtime.rejudge','classroom.runtime.extend',
  'classroom.runtime.unlock','classroom.runtime.rebuild','classroom.runtime.destroy','classroom.release.extend-all',
  'classroom.release.remind-idle','classroom.terminal.assist','classroom.logs.read','classroom.logs.download',
  'classroom.logs.distribute','classroom.readmodel.read'
]
const studentPermissions = ['classroom.lab.start','classroom.lab.read','classroom.lab.submit','classroom.terminal.use','classroom.logs.assignment.read','classroom.logs.assignment.download']

export function classroomHeaders(role: 'teacher' | 'student', extra: HeadersInit = {}): HeadersInit {
  const studentId = localStorage.getItem('yk-student-id') || 'student-a'
  return {
    'Content-Type': 'application/json',
    'X-User-Id': role === 'teacher' ? 'teacher-user' : `user-${studentId}`,
    'X-Role': role,
    'X-Teacher-Id': role === 'teacher' ? 'teacher-a' : '',
    'X-Student-Id': role === 'student' ? studentId : '',
    'X-Permissions': (role === 'teacher' ? teacherPermissions : studentPermissions).join(','),
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
