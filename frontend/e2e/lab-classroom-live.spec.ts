import { expect, test } from '@playwright/test'

const apiBase = process.env.YUEKE_GATE_API_URL || 'http://127.0.0.1:18003'
const courseId = 'course_g7_gate'
const classId = 'class_g7_gate'
const releaseId = 'release_g7_gate'

const teacherHeaders = {
  'X-User-Id': 'teacher-user', 'X-Role': 'teacher', 'X-Teacher-Id': 'teacher-user',
  'X-Permissions': 'classroom.release.read,classroom.runtime.remind,runtime.read',
  'X-Course-Ids': courseId, 'X-Class-Ids': classId,
}
const dispatcherHeaders = {
  'X-User-Id': 'service_contract_dispatcher', 'X-Role': 'admin', 'X-Permissions': 'integration:dispatch',
}

test('真实 MySQL 的 43 人课堂聚合、实时更新与教师处置', async ({ page, request }) => {
  test.skip(process.env.E2E_REAL_CLASSROOM !== '1', '仅在 G7 真实门禁中运行')
  test.setTimeout(60_000)
  await page.addInitScript(values => {
    localStorage.setItem('yk-course-id', values.courseId)
    localStorage.setItem('yk-class-id', values.classId)
    localStorage.setItem('yk-release-id', values.releaseId)
  }, { courseId, classId, releaseId })
  await page.goto('/lab-live')
  await expect(page.getByText('共 43 名学生')).toBeVisible()
  const kpis = page.locator('.kpi')
  await expect(kpis.nth(0)).toContainText('30')
  await expect(kpis.nth(1)).toContainText('10')
  await expect(kpis.nth(2)).toContainText('18')
  await expect(kpis.nth(3)).toContainText('2')
  await expect(kpis.nth(4)).toContainText('13')
  await expect(page.getByRole('row', { name: /验收学生43/ })).toContainText('未开始')

  const row = page.getByRole('row', { name: /验收学生11/ })
  await expect(row).not.toContainText('77 / 100')
  const dispatched = await request.post(`${apiBase}/api/v1/integration/outbox/dispatch?limit=500`, { headers: dispatcherHeaders })
  expect(dispatched.ok(), await dispatched.text()).toBeTruthy()
  const dispatchResult = (await dispatched.json()).results.find((item: any) => item.event_id === 'evt_g7_live_update')
  expect(dispatchResult?.status).toBe('PUBLISHED')
  expect(dispatchResult?.targets).toEqual(['classroom_projection', 'grading_facts'])
  await expect(page.getByTestId('live-state')).toHaveText('实时更新中', { timeout: 10_000 })
  await expect(row).toContainText('4 / 5')
  await expect(row).toContainText('77 / 100')

  await row.getByRole('button', { name: '查看' }).click()
  await page.getByRole('tab', { name: '课堂处置' }).click()
  const actionResponse = page.waitForResponse(response => response.url().includes('/api/v1/classroom/runtime/rti_g7_011/remind') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '提醒', exact: true }).click()
  expect((await actionResponse).status()).toBe(200)
  const logs = await request.get(`${apiBase}/api/v1/runtime-instances/rti_g7_011/logs`, { headers: teacherHeaders })
  expect(logs.ok(), await logs.text()).toBeTruthy()
  expect((await logs.json()).items.some((item: any) => item.event_type === 'runtime.instance.remind')).toBeTruthy()
})
