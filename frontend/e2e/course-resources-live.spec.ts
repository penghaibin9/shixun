import { expect, test } from '@playwright/test'
import ExcelJS from 'exceljs'

test('真实 MySQL 资源目录可由浏览器读取', async ({ page }) => {
  test.skip(process.env.E2E_REAL_API !== '1', '仅在真实后端与 MySQL 验收时运行')
  await page.goto('/resources')
  await expect(page.getByRole('heading', { name: '教学资源生产与课程建设中心' })).toBeVisible()
  await expect(page.getByText('37 / 37')).toBeVisible()
  await expect(page.getByText('12 / 12')).toBeVisible()
  await page.getByRole('link', { name: '课程蓝图', exact: true }).click()
  await expect(page.getByText('7.4')).toBeVisible()
  await expect(page.getByText(/典型数据安全产品选型指南/)).toBeVisible()
  await page.getByRole('link', { name: '完整性审计', exact: true }).click()
  await expect(page.getByText('196')).toBeVisible()
  await expect(page.getByText('真实阻断项')).toBeVisible()
})

test('浏览器上传真实文件并建立草稿版本', async ({ page }) => {
  test.skip(process.env.E2E_REAL_API !== '1', '仅在真实后端与 MySQL 验收时运行')
  const suffix = Date.now().toString()
  await page.goto('/resources')
  await page.getByRole('button', { name: '＋ 新增资源' }).click()
  await page.getByPlaceholder('例如：第 1.1 课时演示文稿').fill(`浏览器上传讲义 ${suffix}`)
  await page.locator('input[type="file"]').setInputFiles({ name: `lesson-${suffix}.pptx`, mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', buffer: Buffer.from(`PK\u0003\u0004playwright-${suffix}`) })
  await page.getByRole('button', { name: '上传并建立草稿版本' }).click()
  await expect(page.getByText('真实文件已上传并登记为草稿版本')).toBeVisible()
  const row = page.getByRole('row').filter({ hasText: `浏览器上传讲义 ${suffix}` })
  await expect(row).toContainText('PPT（演示文稿）')
  await expect(row).toContainText('草稿')
  await expect(row.getByRole('button', { name: '下载' })).toBeVisible()
})

test('真实浏览器完成 196 行题库导入并由独立审核人发布', async ({ page }, testInfo) => {
  test.skip(process.env.E2E_REAL_API !== '1', '仅在专属空白 MySQL 验收库运行')
  test.setTimeout(120_000)

  await page.goto('/course-questions')
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载 XLSX（电子表格）模板' }).click()
  const download = await downloadPromise
  const downloadedPath = await download.path()
  if (!downloadedPath) throw new Error('题库模板下载路径不可用')

  const workbook = new ExcelJS.Workbook()
  await workbook.xlsx.readFile(downloadedPath)
  const sheet = workbook.getWorksheet('题目导入')
  if (!sheet) throw new Error('题库模板缺少“题目导入”工作表')
  for (let rowNumber = 2; rowNumber <= 197; rowNumber += 1) {
    const questionType = String(sheet.getCell(rowNumber, 3).value || '')
    sheet.getCell(rowNumber, 4).value = `真实浏览器导入题 ${rowNumber - 1}`
    sheet.getCell(rowNumber, 10).value = '真实浏览器导入解析'
    if (questionType === '填空') sheet.getCell(rowNumber, 9).value = '参考答案'
    if (questionType === '单选') {
      sheet.getCell(rowNumber, 5).value = '正确选项'
      sheet.getCell(rowNumber, 6).value = '干扰选项'
      sheet.getCell(rowNumber, 9).value = 'A'
    }
    if (questionType === '多选') {
      sheet.getCell(rowNumber, 5).value = '正确选项一'
      sheet.getCell(rowNumber, 6).value = '正确选项二'
      sheet.getCell(rowNumber, 7).value = '干扰选项'
      sheet.getCell(rowNumber, 9).value = 'A,B'
    }
    if (questionType === '判断') sheet.getCell(rowNumber, 9).value = 'A'
  }
  const importPath = testInfo.outputPath('question-bank-196.xlsx')
  await workbook.xlsx.writeFile(importPath)

  await page.getByRole('button', { name: '批量导入题目' }).click()
  await page.getByLabel('选择题库文件').setInputFiles(importPath)
  await page.getByRole('button', { name: '开始导入' }).click()
  await expect(page.getByText('已导入 196 道题目，全部进入独立审核队列。')).toBeVisible()
  await expect(page.getByRole('tab', { name: '待审核（196）' })).toBeVisible()
  await page.getByRole('tab', { name: '待审核（196）' }).click()
  const ownQuestion = page.getByRole('cell', { name: '真实浏览器导入题 1', exact: true }).locator('..')
  await expect(ownQuestion.getByText('需其他审核人')).toBeVisible()

  await page.route('**/api/v1/**', async route => {
    await route.continue({
      headers: {
        ...route.request().headers(),
        'x-user-id': 'reviewer_b',
        'x-teacher-id': 'reviewer_b',
      },
    })
  })
  await page.reload()
  await page.getByRole('tab', { name: '待审核（196）' }).click()
  const reviewableQuestion = page.getByRole('cell', { name: '真实浏览器导入题 1', exact: true }).locator('..')
  await reviewableQuestion.getByRole('button', { name: '审核' }).click()
  await expect(page.getByRole('dialog', { name: '题目独立审核' })).toContainText('真实浏览器导入解析')
  await page.getByRole('button', { name: '确认通过并发布' }).click()
  await expect(page.getByText('题目已通过审核并发布。')).toBeVisible()
  await expect(page.getByRole('tab', { name: '待审核（195）' })).toBeVisible()
})
