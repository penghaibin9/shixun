import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test, type APIRequestContext, type APIResponse } from '@playwright/test'

const apiBase = process.env.YUEKE_GATE_API_URL || 'http://127.0.0.1:18003'
const imageDigest = process.env.YUEKE_GATE_IMAGE_DIGEST || ''
const internalToken = process.env.YUEKE_INTERNAL_RUNTIME_TOKEN || ''

async function checked<T = any>(response: APIResponse): Promise<T> {
  if (!response.ok()) throw new Error(`${response.url()} -> ${response.status()}: ${await response.text()}`)
  return response.json() as Promise<T>
}

function identity(permissions: string[], courseId = '', classId = '', studentId = '') {
  return {
    'X-User-Id': studentId ? `user-${studentId}` : 'teacher-browser-gate',
    'X-Role': studentId ? 'student' : 'teacher',
    'X-Teacher-Id': studentId ? '' : 'teacher-browser-gate',
    'X-Student-Id': studentId,
    'X-Permissions': permissions.join(','),
    'X-Course-Ids': courseId,
    'X-Class-Ids': classId,
  }
}

async function prepare(request: APIRequestContext) {
  const run = Date.now().toString(36)
  const teachingBase = identity(['teaching.course.write', 'teaching.class.write', 'teaching.members.write'])
  const course = await checked<any>(await request.post(`${apiBase}/api/v1/courses`, { headers: teachingBase, data: { name: `浏览器终端门禁-${run}`, term: '2026 秋季' } }))
  const courseId = course.course_id as string
  const teachingCourse = identity(['teaching.class.write', 'teaching.members.write'], courseId)
  const classroom = await checked<any>(await request.post(`${apiBase}/api/v1/classes`, { headers: teachingCourse, data: { name: `浏览器门禁班-${run}`, term: '2026 秋季', course_id: courseId } }))
  const classId = classroom.class_id as string
  const studentId = `student-browser-${run}`
  await checked(await request.post(`${apiBase}/api/v1/classes/${classId}/members`, {
    headers: identity(['teaching.members.write'], courseId, classId),
    data: { student_id: studentId, student_number: `B${run}`, student_name: '浏览器终端学生' },
  }))

  const spec = JSON.parse(readFileSync(resolve(process.cwd(), '../backend/app/labs/fixtures/rsa-v1.json'), 'utf8'))
  spec.lab_definition_id = `lab_browser_${run}`
  spec.name = 'RSA 浏览器终端门禁实验'
  for (const node of spec.nodes) {
    node.image_id = 'img_python_openssl_gate'
    node.image_digest = imageDigest
  }
  for (const binding of spec.image_bindings) {
    binding.infra_image_id = 'img_python_openssl_gate'
    binding.digest = imageDigest
  }
  for (const checkpoint of spec.checkpoints) checkpoint.checkpoint_id = `${checkpoint.checkpoint_id}_${run}`
  const labHeaders = { ...identity(['labs.read', 'labs.write', 'labs.publish', 'runtime.read', 'infrastructure.read', 'infrastructure.write'], courseId, classId), 'X-Idempotency-Key': `browser-create-${run}` }
  const lab = await checked<any>(await request.post(`${apiBase}/api/v1/labs`, { headers: labHeaders, data: { course_id: courseId, code: `RSA-BROWSER-${run}`, category: '密码学', objective: '验证真实浏览器终端。', spec } }))
  const versionId = lab.latest_version.lab_version_id as string
  await checked(await request.post(`${apiBase}/api/v1/lab-versions/${versionId}/validate`, { headers: { ...labHeaders, 'X-Idempotency-Key': `browser-validate-${run}` } }))
  await checked(await request.post(`${apiBase}/api/v1/lab-versions/${versionId}/publish`, { headers: { ...labHeaders, 'X-Idempotency-Key': `browser-publish-${run}` } }))
  await checked(await request.post(`${apiBase}/api/v1/infrastructure/images`, {
    headers: labHeaders,
    data: { image_id: 'img_python_openssl_gate', name: 'Python OpenSSL 门禁镜像', tag: '3.11-bookworm', digest: imageDigest, size_bytes: 0, scan_status: 'PASSED', startup_check_status: 'PASSED', teaching_validation_status: 'PASSED', enabled: true },
  }))
  await checked(await request.post(`${apiBase}/api/v1/infrastructure/nodes`, {
    headers: labHeaders,
    data: { node_id: 'node_docker_desktop_gate', name: 'Docker Desktop Linux 门禁节点', agent_url: 'http://127.0.0.1:19443', weight: 1000, labels: { environment: 'browser-gate' } },
  }))
  const releaseId = `release_browser_${run}`
  await checked(await request.post(`${apiBase}/api/v1/runtime/release-contexts`, {
    headers: { Authorization: `Bearer ${internalToken}` },
    data: { lab_release_id: releaseId, lab_version_id: versionId, course_id: courseId, class_id: classId, status: 'OPEN' },
  }))
  return { courseId, classId, studentId, releaseId }
}

test('真实浏览器启动容器并通过网页终端执行命令', async ({ page, request }) => {
  test.skip(process.env.E2E_REAL_RUNTIME !== '1', '仅在真实 Docker 浏览器门禁中运行')
  test.setTimeout(120_000)
  expect(imageDigest).toMatch(/^sha256:[0-9a-f]{64}$/)
  expect(internalToken).not.toBe('')
  const context = await prepare(request)
  const studentRuntimeHeaders = identity(['runtime.read', 'runtime.destroy'], context.courseId, context.classId, context.studentId)
  let runtimeInstanceId = ''
  try {
    await page.addInitScript(values => {
      localStorage.setItem('yk-course-id', values.courseId)
      localStorage.setItem('yk-class-id', values.classId)
      localStorage.setItem('yk-student-id', values.studentId)
      localStorage.setItem('yk-release-id', values.releaseId)
    }, context)
    await page.goto('/student-lab')
    await expect(page.getByRole('button', { name: '启动实验' })).toBeVisible()
    await page.getByRole('button', { name: '启动实验' }).click()
    await expect(page.getByText('交互终端 · 已连接')).toBeVisible({ timeout: 45_000 })
    const terminal = page.getByRole('textbox', { name: '实验终端' })
    await terminal.focus()
    await page.keyboard.type('echo BROWSER_TERMINAL_OK')
    await page.keyboard.press('Enter')
    await expect(terminal).toContainText('BROWSER_TERMINAL_OK', { timeout: 15_000 })
    const students = await checked<any>(await request.get(`${apiBase}/api/v1/runtime/lab-releases/${context.releaseId}/students`, { headers: studentRuntimeHeaders }))
    runtimeInstanceId = students.items[0].runtime_instance_id
    expect(runtimeInstanceId).toBeTruthy()
  } finally {
    if (runtimeInstanceId) {
      await checked(await request.post(`${apiBase}/api/v1/runtime-instances/${runtimeInstanceId}/destroy`, { headers: studentRuntimeHeaders, data: { reason: '浏览器终端门禁完成回收' } }))
    }
  }
})
