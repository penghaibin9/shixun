import { readFile } from 'node:fs/promises'
import { expect, test } from '@playwright/test'

const courseId = 'course_g8_gate'
const classId = 'class_g8_gate'
const lessonId = 'lesson_g8_gate'
const studentId = 'student_g8_001'

test('真实 MySQL 成绩到学情再到归档的浏览器主链', async ({ page, request }, testInfo) => {
  test.skip(process.env.E2E_REAL_GRADING !== '1', '仅真实 G8 验收时运行')
  await page.addInitScript(({ courseId, classId, lessonId, studentId }) => {
    localStorage.setItem('yk-course-id', courseId)
    localStorage.setItem('yk-class-id', classId)
    localStorage.setItem('yk-lesson-id', lessonId)
    localStorage.setItem('yk-student-id', studentId)
  }, { courseId, classId, lessonId, studentId })

  const dispatchResponse = await request.post('/api/v1/integration/outbox/dispatch?limit=100', {
    headers: {
      'X-User-Id': 'service_g8_gate',
      'X-Role': 'admin',
      'X-Permissions': 'integration:dispatch',
    },
  })
  expect(dispatchResponse.ok()).toBeTruthy()
  const dispatch = await dispatchResponse.json()
  expect(dispatch).toMatchObject({ selected: 14, published: 14, failed: 0 })

  page.on('dialog', dialog => dialog.accept())
  await page.goto('/teacher-grades')
  await expect(page.getByRole('heading', { name: '成绩管理' })).toBeVisible()
  await page.getByRole('button', { name: '重新计算' }).click()
  await expect(page.locator('.score-hero')).toHaveText('就绪')
  const firstStudent = page.locator('tbody tr').filter({ hasText: 'student_g8_001' })
  const secondStudent = page.locator('tbody tr').filter({ hasText: 'student_g8_002' })
  await expect(firstStudent).toContainText('94')
  await expect(secondStudent).toContainText('68')

  await firstStudent.getByRole('button', { name: '追溯' }).click()
  await expect(page.getByText('成绩来源追溯 · student_g8_001')).toBeVisible()
  await expect(page.getByText('总评 94')).toBeVisible()
  await expect(page.getByText('实验提交', { exact: false }).first()).toBeVisible()
  await page.getByRole('button', { name: '确认成绩入账' }).click()
  await expect(page.getByText('已入账', { exact: true })).toBeVisible()

  await page.getByRole('link', { name: '学情分析' }).click()
  await expect(page.getByRole('heading', { name: '学情分析' })).toBeVisible()
  await expect(page.getByText('81', { exact: true })).toBeVisible()
  await expect(page.getByText('到课率偏低')).toBeVisible()
  await page.getByRole('button', { name: '② 按小节' }).click()
  await expect(page.getByText('平均成绩：80')).toBeVisible()
  await page.getByRole('button', { name: '③ 实验维度' }).click()
  await expect(page.getByText('release_g8_gate')).toBeVisible()
  await expect(page.getByText('90', { exact: true })).toBeVisible()

  await page.getByRole('link', { name: '课程归档' }).click()
  await page.getByRole('button', { name: '归档预检' }).click()
  for (const label of ['学生名单已冻结', '名单人数与成绩册一致', '成绩已入账', '成绩来源可追溯', '实验判分证据已引用', '课程资源已冻结']) {
    await expect(page.getByText(label, { exact: true })).toBeVisible()
  }
  await expect(page.getByText('阻断', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '冻结归档' }).click()
  await expect(page.getByText('已归档', { exact: true })).toBeVisible()
  await expect(page.getByText('实验日志与判分证据引用')).toBeVisible()

  const xlsxDownload = page.waitForEvent('download')
  await page.getByTestId('archive-download-GRADEBOOK_XLSX').click()
  const xlsx = await xlsxDownload
  const xlsxPath = testInfo.outputPath('archive-gradebook.xlsx')
  await xlsx.saveAs(xlsxPath)
  expect((await readFile(xlsxPath)).subarray(0, 2).toString()).toBe('PK')

  const manifestDownload = page.waitForEvent('download')
  await page.getByTestId('archive-download-RESOURCE_VERSION_MANIFEST_JSON').click()
  const manifest = await manifestDownload
  const manifestPath = testInfo.outputPath('resource-manifest.json')
  await manifest.saveAs(manifestPath)
  const manifestData = JSON.parse(await readFile(manifestPath, 'utf8'))
  expect(manifestData.delivery_manifests[0].manifest_id).toBe('manifest_g8_gate')

  await page.getByRole('link', { name: '我的成绩' }).click()
  await expect(page.getByRole('heading', { name: '我的成绩' })).toBeVisible()
  await expect(page.getByText('94', { exact: true })).toBeVisible()
  await expect(page.getByText('1', { exact: true })).toBeVisible()
  await expect(page.getByText('就绪', { exact: true })).toBeVisible()

  await page.getByRole('link', { name: '审计日志' }).click()
  await expect(page.getByRole('heading', { name: '审计日志' })).toBeVisible()
  await expect(page.locator('tbody tr').filter({ hasText: '成绩已入账' })).toBeVisible()
  await expect(page.locator('tbody tr').filter({ hasText: '课程已归档' })).toBeVisible()
})
