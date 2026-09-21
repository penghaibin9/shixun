import { expect, test } from '@playwright/test'

test('教师工作台可在浏览器中加载并导航至教学闭环', async ({ page }) => {
  await page.goto('/teacher-dashboard')
  await expect(page.getByRole('heading', { name: '教师工作台' })).toBeVisible()
  await page.getByRole('link', { name: '教学闭环' }).click()
  await expect(page.getByRole('heading', { name: '完整教学闭环' })).toBeVisible()
  await expect(page.getByText('课程归档 — 待业务模块接入', { exact: true })).toBeVisible()
})
