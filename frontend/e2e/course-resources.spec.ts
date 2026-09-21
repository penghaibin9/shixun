import { expect, test } from '@playwright/test'

const theory = Array.from({ length: 37 }, (_, index) => ({ course_id: 'course_data_security', lesson_id: `t${index}`, lesson_kind: 'THEORY', chapter_no: index < 5 ? 1 : index < 8 ? 2 : index < 14 ? 3 : index < 21 ? 4 : index < 28 ? 5 : index < 33 ? 6 : 7, lesson_code: index === 36 ? '7.4' : `${Math.floor(index / 6) + 1}.${index + 1}`, title: index === 36 ? '典型数据安全产品选型指南（加密类/脱敏类/审计类/管控类/备份类）' : `理论知识点 ${index + 1}`, purpose: null, environment: null, principle: null, steps_summary: null, core_experiment: null }))
const labs = Array.from({ length: 12 }, (_, index) => ({ course_id: 'course_data_security', lesson_id: `l${index}`, lesson_kind: 'LAB', chapter_no: null, lesson_code: `实验${String(index + 1).padStart(2, '0')}`, title: `实验主题 ${index + 1}`, purpose: '掌握实验核心操作', environment: '隔离实验环境', principle: '理解核心原理', steps_summary: '准备、执行、验证、复盘', core_experiment: index < 2 ? 'AES/DES' : index < 4 ? 'RSA' : '综合实践' }))
const audit = { course_id: 'course_data_security', total: 196, pass: 12, warning: 0, blocking: 184, blocking_items: ['1.1 缺少PPT', '实验01 缺少实验文件'], procurement_mapping: [{ requirement: '理论课程资源', owner: 'B', evidence: '37 理论课时资源门禁' }] }

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const url = route.request().url()
    let body: unknown = { items: [], total: 0 }
    if (url.includes('course-blueprint')) body = { items: [...theory, ...labs], total: 49, chapter_counts: {} }
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
