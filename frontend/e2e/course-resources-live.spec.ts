import { expect, test } from '@playwright/test'

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
