import { expect, test } from '@playwright/test'

test('G3：模板到 RSA 不可变版本与 JSON 导出', async ({ page }) => {
  test.skip(process.env.E2E_REAL_API !== '1', '仅在真实后端与 MySQL 验收时运行')
  await page.goto('/labs')
  await expect(page.getByText('AES（高级加密标准）/DES（数据加密标准）基础加解密', { exact: true })).toBeVisible()
  await expect(page.getByText('数据安全治理综合实践', { exact: true })).toBeVisible()
  expect(await page.locator('.lab-card').count()).toBeGreaterThanOrEqual(12)
  await page.goto('/lab-templates')
  await expect(page.getByRole('heading', { name: '实验模板库' })).toBeVisible()
  const cryptoTemplate = page.locator('.template-card').filter({ hasText: '双机密码学实验' })
  await expect(cryptoTemplate).toBeVisible()
  await cryptoTemplate.getByRole('link', { name: '查看模板示例定义' }).click()

  await expect(page.getByRole('heading', { name: '创建实验 · 完整 6 步设计器' })).toBeVisible()
  await expect(page.getByText('RSA 非对称加密算法实验', { exact: true })).toBeVisible()
  const clone = page.getByRole('button', { name: '从已发布版本创建可编辑草稿' })
  if (await clone.isVisible()) await clone.click()

  await page.locator('.builder-steps').getByRole('button', { name: /场景拓扑/ }).click()
  await expect(page.getByText('student-rsa', { exact: true })).toBeVisible()
  await expect(page.getByText('target-rsa', { exact: true })).toBeVisible()
  await expect(page.getByText('学生隔离', { exact: true })).toBeVisible()

  await page.locator('.builder-steps').getByRole('button', { name: /Docker 镜像/ }).click()
  await expect(page.locator('.digest').first()).toContainText('sha256:')

  await page.locator('.builder-steps').getByRole('button', { name: /DAG 与判分/ }).click()
  await expect(page.getByText('6. 提交实验报告')).toBeVisible()
  await expect(page.getByText('5 个得分点')).toBeVisible()
  await expect(page.getByText('100 / 100')).toBeVisible()

  await page.getByRole('button', { name: '发布前检查' }).click()
  await expect(page.getByText(/发布门禁通过/)).toBeVisible()
  await page.locator('.builder-steps').getByRole('button', { name: /教师预演/ }).click()
  await page.getByRole('button', { name: /发布并冻结/ }).click()
  await expect(page.getByText(/已发布并冻结/)).toBeVisible()
  await expect(page.getByText(/版本已冻结，不可覆盖/)).toBeVisible()

  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出实验配置' }).click()
  const file = await download
  expect(file.suggestedFilename()).toMatch(/lab_rsa-v\d+\.json/)
})

