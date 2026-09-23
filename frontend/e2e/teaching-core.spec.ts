import { expect, test } from '@playwright/test'
import ExcelJS from 'exceljs'


test('G1/G2 与学生管理、投票、作业测验真实主链', async ({ page, browser, request }, testInfo) => {
  test.skip(process.env.E2E_REAL_API !== '1', '仅在真实后端与 MySQL 验收时运行')
  const workbook = new ExcelJS.Workbook()
  const sheet = workbook.addWorksheet('学生导入')
  sheet.addRow(['学号*', '姓名*', '班级', '手机号（可选）', '邮箱（可选）'])
  const run = Date.now().toString().slice(-7)
  for (let index = 1; index <= 43; index += 1) sheet.addRow([`${run}${String(index).padStart(2, '0')}`, `浏览器学生${index}`, '网络安全 2301 班', '', ''])
  const filePath = testInfo.outputPath('students-43.xlsx')
  await workbook.xlsx.writeFile(filePath)
  const badWorkbook = new ExcelJS.Workbook()
  const badSheet = badWorkbook.addWorksheet('学生导入')
  badSheet.addRow(['学号*', '姓名*', '班级', '手机号（可选）', '邮箱（可选）'])
  badSheet.addRow([`${run}01`, '重复学生', '网络安全 2301 班', '', ''])
  badSheet.addRow(['=2+2', '公式风险', '网络安全 2301 班', '', ''])
  const badFilePath = testInfo.outputPath('students-errors.xlsx')
  await badWorkbook.xlsx.writeFile(badFilePath)

  const adminHeaders = { 'X-User-Id': `browser-roster-admin-${run}`, 'X-Role': 'admin', 'X-Permissions': 'auth.accounts.write' }
  for (let index = 1; index <= 43; index += 1) {
    const response = await request.post('/api/v1/auth/users', {
      headers: adminHeaders,
      data: { display_name: `浏览器学生${index}`, role: 'student', login_name: `browser-student-${run}-${index}`, student_number: `${run}${String(index).padStart(2, '0')}` },
    })
    expect(response.ok(), await response.text()).toBeTruthy()
  }

  await page.goto('/courses')
  await page.evaluate(() => localStorage.clear())
  await page.reload()
  await page.getByRole('button', { name: '＋ 新建课程' }).click()
  await expect(page.getByTestId('message')).toContainText('课程已创建')
  await page.getByRole('button', { name: '＋ 建班' }).click()
  await expect(page.getByTestId('message')).toContainText('班级已创建')
  await page.getByLabel('选择学生名单').setInputFiles(filePath)
  await page.getByRole('button', { name: '导入学生' }).click()
  await expect(page.getByTestId('message')).toContainText('成功 43 人')
  await page.getByLabel('选择学生名单').setInputFiles(badFilePath)
  await page.getByRole('button', { name: '导入学生' }).click()
  await expect(page.getByTestId('message')).toContainText('失败 2 人')
  const errorDownload = page.waitForEvent('download')
  await page.getByTestId('import-error-download').click()
  expect((await errorDownload).suggestedFilename()).toBe('student-import-errors.xlsx')

  await page.goto('/teacher-students')
  await expect(page.getByRole('heading', { name: '学生管理' })).toBeVisible()
  await expect(page.getByText('共 43 人')).toBeVisible()
  await page.getByPlaceholder('输入姓名或学号').fill('浏览器学生1')
  await page.getByRole('button', { name: '查询' }).click()
  await expect(page.getByRole('cell', { name: '浏览器学生1', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '查看详情' }).first().click()
  await expect(page.getByRole('dialog', { name: '学生详情' })).toContainText('数据待汇总')
  await page.getByRole('button', { name: '关闭' }).click()

  const teachingScope = await page.evaluate(() => ({
    courseId: localStorage.getItem('yk-course-id'),
    classId: localStorage.getItem('yk-class-id'),
  }))
  expect(teachingScope.courseId).toBeTruthy()
  expect(teachingScope.classId).toBeTruthy()
  const lessonResponse = await request.get(`/api/v1/courses/${teachingScope.courseId}/lessons`, {
    headers: {
      'X-User-Id': 'teacher-a',
      'X-Role': 'teacher',
      'X-Teacher-Id': 'teacher-a',
      'X-Permissions': 'teaching.course.read',
      'X-Course-Ids': teachingScope.courseId!,
      'X-Class-Ids': teachingScope.classId!,
    },
  })
  expect(lessonResponse.ok(), await lessonResponse.text()).toBeTruthy()
  const lessonId = (await lessonResponse.json()).items[0]?.lesson_id
  expect(lessonId).toBeTruthy()
  const questionAuthorHeaders = {
    'X-User-Id': `browser-question-author-${run}`,
    'X-Role': 'teacher',
    'X-Teacher-Id': `browser-question-author-${run}`,
    'X-Permissions': 'resources:read,resources:write',
    'X-Course-Ids': teachingScope.courseId!,
  }
  const createdQuestion = await request.post('/api/v1/questions', {
    headers: questionAuthorHeaders,
    data: {
      course_id: teachingScope.courseId,
      lesson_id: lessonId,
      question_type: 'SINGLE',
      stem: `浏览器真实题目 ${run}：RSA 中公开给通信对方的是哪一类密钥？`,
      answer: ['A'],
      explanation: '公开给通信对方的是公钥。',
      options: [
        { key: 'A', text: '公钥', is_correct: true },
        { key: 'B', text: '私钥', is_correct: false },
      ],
    },
  })
  expect(createdQuestion.ok(), await createdQuestion.text()).toBeTruthy()
  const questionId = (await createdQuestion.json()).question_id
  expect(questionId).toBeTruthy()
  const reviewedQuestion = await request.post(`/api/v1/questions/${questionId}/review`, {
    headers: {
      'X-User-Id': `browser-question-reviewer-${run}`,
      'X-Role': 'teacher',
      'X-Teacher-Id': `browser-question-reviewer-${run}`,
      'X-Permissions': 'resources:read,resources:review',
      'X-Course-Ids': teachingScope.courseId!,
    },
    data: { decision: 'APPROVED' },
  })
  expect(reviewedQuestion.ok(), await reviewedQuestion.text()).toBeTruthy()

  await page.goto('/attendance-management')
  await page.getByRole('button', { name: '发布签到' }).click()
  await expect(page.getByTestId('attendance-message')).toContainText('签到已发布')
  const signUrl = await page.getByTestId('attendance-link').getAttribute('href')
  const studentId = await page.evaluate(() => localStorage.getItem('yk-student-id'))
  expect(signUrl).toContain('/student-attendance/')
  expect(studentId).toBeTruthy()
  const studentContext = await browser.newContext()
  await studentContext.addInitScript(id => localStorage.setItem('yk-student-id', id), studentId!)
  const studentPage = await studentContext.newPage()
  await studentPage.goto(signUrl!)
  await expect(studentPage.getByText('RSA 数字签名课堂签到')).toBeVisible()
  await studentPage.getByRole('button', { name: '立即签到' }).click()
  await expect(studentPage.getByText('签到成功')).toBeVisible()
  await studentContext.close()
  await page.goto('/attendance-management')
  await page.getByRole('button', { name: '刷新结果' }).click()
  await expect(page.locator('.kpi').nth(1)).toContainText('1')

  await page.goto('/teacher-assignments')
  await page.getByRole('button', { name: '发布投票' }).click()
  await expect(page.getByTestId('work-message')).toContainText('投票已发布')
  const questionChoice = page.getByTestId(`published-question-${questionId}`)
  await expect(questionChoice).toBeVisible()
  await questionChoice.getByRole('checkbox').click()
  await page.getByRole('button', { name: '＋ 发布课后作业与小测' }).click()
  await expect(page.getByTestId('work-message')).toContainText('作业与测验已发布')
  await page.goto('/student-quiz')
  await page.getByRole('button', { name: '提交当前课堂投票' }).click()
  await expect(page.getByTestId('student-work-message')).toContainText('课堂投票已提交')
  const assignmentTask = page.locator('[data-testid^="assignment-task-"]').first()
  await expect(assignmentTask).toBeVisible()
  await assignmentTask.getByRole('radio', { name: 'A. 公钥' }).click()
  await assignmentTask.getByRole('button', { name: '提交作业' }).click()
  await expect(page.getByTestId('student-work-message')).toContainText('作业已提交')
  const quizTask = page.locator('[data-testid^="quiz-task-"]').first()
  await expect(quizTask).toBeVisible()
  await quizTask.getByRole('radio', { name: 'A. 公钥' }).click()
  await quizTask.getByRole('button', { name: '开始并提交测验' }).click()
  await expect(page.getByTestId('student-work-message')).toContainText('课堂小测已提交')
  await page.goto('/teacher-assignments')
  await page.getByRole('button', { name: '查看统计' }).click()
  await expect(page.getByText('1 人')).toBeVisible()
})
