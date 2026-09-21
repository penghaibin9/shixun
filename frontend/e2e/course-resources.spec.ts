import { expect, test } from '@playwright/test'

const theory = Array.from({ length: 37 }, (_, index) => ({ course_id: 'course_data_security', lesson_id: `t${index}`, lesson_kind: 'THEORY', chapter_no: index < 5 ? 1 : index < 8 ? 2 : index < 14 ? 3 : index < 21 ? 4 : index < 28 ? 5 : index < 33 ? 6 : 7, lesson_code: index === 36 ? '7.4' : `${Math.floor(index / 6) + 1}.${index + 1}`, title: index === 36 ? '典型数据安全产品选型指南（加密类/脱敏类/审计类/管控类/备份类）' : `理论知识点 ${index + 1}`, purpose: null, environment: null, principle: null, steps_summary: null, core_experiment: null }))
const labs = Array.from({ length: 12 }, (_, index) => ({ course_id: 'course_data_security', lesson_id: `l${index}`, lesson_kind: 'LAB', chapter_no: null, lesson_code: `实验${String(index + 1).padStart(2, '0')}`, title: `实验主题 ${index + 1}`, purpose: '掌握实验核心操作', environment: '隔离实验环境', principle: '理解核心原理', steps_summary: '准备、执行、验证、复盘', core_experiment: index < 2 ? 'AES/DES' : index < 4 ? 'RSA' : '综合实践' }))
const audit = { course_id: 'course_data_security', total: 196, pass: 12, warning: 0, blocking: 184, blocking_items: ['1.1 缺少PPT', '实验01 缺少实验文件'], procurement_mapping: [{ requirement: '理论课程资源', owner: 'B', evidence: '37 理论课时资源门禁' }] }
const readiness = { course_id: 'course_data_security', theory_lessons: 37, lab_lessons: 12, ppt: { ready: 0, required: 37 }, theory_video: { ready: 0, required: 37 }, lab_file: { ready: 0, required: 12 }, lab_video: { ready: 0, required: 12 }, question_lessons: { ready: 0, required: 49 }, published_questions: { ready: 0, required: 196 }, blocking: 196 }
const importJob = { job_id: 'job-196', status: 'VALIDATION_FAILED', total_count: 196, imported_count: 0, error_count: 2, review_queue_count: 0, original_filename: 'questions.xlsx', error_rows: [{ row_number: 8, field: '课时编号', code: 'UNKNOWN_LESSON', message: '课时编号不存在' }, { row_number: 19, field: '正确答案*', code: 'ANSWER_REQUIRED', message: '答案不能为空' }] }
let reviewItems: Array<Record<string, unknown>> = []

test.beforeEach(async ({ page }) => {
  reviewItems = [
    { question_id: 'q-own', lesson_id: 't0', lesson_code: '1.1', question_type: 'SINGLE', stem: '本人创建的单选题', options: [], answer: ['A'], explanation: '解析完整', status: 'PENDING_REVIEW', created_by: 'teacher_b', created_at: '2026-09-21T10:00:00', source_row_number: 2 },
    { question_id: 'q-other', lesson_id: 't0', lesson_code: '1.1', question_type: 'TRUE_FALSE', stem: '其他教师提交的判断题', options: [], answer: ['正确'], explanation: '解析完整', status: 'PENDING_REVIEW', created_by: 'teacher_a', created_at: '2026-09-21T10:01:00', source_row_number: 3 },
  ]
  await page.route('**/api/v1/**', async route => {
    const url = route.request().url()
    const method = route.request().method()
    let body: unknown = { items: [], total: 0 }
    if (url.includes('questions/import-template.xlsx')) return route.fulfill({ status: 200, contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers: { 'Content-Disposition': 'attachment; filename="question-import-template.xlsx"' }, body: Buffer.from([80, 75, 3, 4]) })
    if (url.includes('questions/import-jobs/job-196/error-rows.xlsx')) return route.fulfill({ status: 200, contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', body: Buffer.from([80, 75, 3, 4]) })
    if (url.endsWith('/questions/import') && method === 'POST') body = importJob
    else if (url.includes('questions/import-jobs/job-196')) body = importJob
    else if (url.includes('questions/review-queue')) body = { items: reviewItems, page: 1, page_size: reviewItems.length, total: reviewItems.length }
    else if (url.endsWith('/questions/q-other/review') && method === 'POST') { reviewItems = reviewItems.filter(item => item.question_id !== 'q-other'); body = { question_id: 'q-other', status: 'PUBLISHED', reviewed_by: 'teacher_b' } }
    else if (url.includes('course-blueprint')) body = { items: [...theory, ...labs], total: 49, chapter_counts: {} }
    else if (url.includes('resources/readiness')) body = readiness
    else if (url.includes('questions/coverage')) body = { items: [...theory, ...labs].map(x => ({ lesson_id: x.lesson_id, lesson_code: x.lesson_code, types: [], passed: false })), total: 49, passed: 0 }
    else if (url.includes('audit')) body = audit
    else if (url.includes('manifest.json')) body = { status: 'BLOCKED', version_no: null, theory_lessons: 37, lab_lessons: 12, audit, content_declaration: '目录结构已建立；真实文件待上传。' }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
})

test('资源主链可从总览依次到交付页', async ({ page }) => {
  await page.goto('/resources')
  await expect(page.getByRole('heading', { name: '教学资源生产与课程建设中心' })).toBeVisible()
  const path: [string, string][] = [['课程蓝图', '课程蓝图'], ['理论课时', '理论课时资源'], ['PPT / 讲义', 'PPT / 课时讲义'], ['视频中心', '视频中心'], ['题库中心', '题库中心'], ['实验课时', '实验课程资源'], ['完整性审计', '资源完整性审计'], ['采购条款映射', '采购条款映射'], ['发布与交付', '发布与最终交付']]
  for (const [link, heading] of path) {
    await page.getByRole('link', { name: link, exact: true }).click()
    await expect(page.getByRole('heading', { name: heading })).toBeVisible()
  }
  await expect(page.getByText('存在阻断', { exact: true })).toBeVisible()
  await expect(page.getByText('阻断项').last()).toBeVisible()
})

test('题库模板、196 行导入、逐行错误与独立审核形成闭环', async ({ page }) => {
  await page.goto('/course-questions')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载 XLSX（电子表格）模板' }).click()
  await expect((await download).suggestedFilename()).toBe('question-import-template.xlsx')

  await page.getByRole('button', { name: '批量导入题目' }).click()
  await page.getByLabel('选择题库文件').setInputFiles({ name: 'questions.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from([80, 75, 3, 4]) })
  await page.getByRole('button', { name: '开始导入' }).click()
  await expect(page.getByText('文件校验未通过，尚未写入题库')).toBeVisible()
  await expect(page.getByText('196', { exact: true })).toBeVisible()
  await expect(page.getByText('第 8 行', { exact: true })).toBeVisible()
  await expect(page.getByText('课时编号不存在', { exact: true })).toBeVisible()
  await expect(page.getByText('第 19 行', { exact: true })).toBeVisible()
  const errorDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载错误明细' }).click()
  await expect((await errorDownload).suggestedFilename()).toBe('question-import-errors-job-196.xlsx')

  await page.getByRole('tab', { name: /待审核/ }).click()
  const ownRow = page.getByRole('row').filter({ hasText: '本人创建的单选题' })
  await expect(ownRow.getByText('需其他审核人')).toBeVisible()
  await expect(ownRow.getByRole('button', { name: '审核' })).toHaveCount(0)
  const otherRow = page.getByRole('row').filter({ hasText: '其他教师提交的判断题' })
  await otherRow.getByRole('button', { name: '审核' }).click()
  await expect(page.getByRole('dialog', { name: '题目独立审核' })).toContainText('解析完整')
  await page.getByRole('button', { name: '确认通过并发布' }).click()
  await expect(page.getByText('题目已通过审核并发布')).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: '其他教师提交的判断题' })).toHaveCount(0)
})
