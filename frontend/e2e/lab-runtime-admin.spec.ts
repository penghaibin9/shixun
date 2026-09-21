import { expect, test } from '@playwright/test'

test('D 线管理员基础设施页面读取真实 API 事实', async ({ page }) => {
  test.skip(process.env.E2E_REAL_RUNTIME !== '1', '仅在真实 Docker 浏览器门禁中运行')
  await page.goto('/admin/overview')
  await expect(page.getByRole('heading', { name: '运行总览' })).toBeVisible()
  await expect(page.getByText('运行实例', { exact: true })).toBeVisible()
  await expect(page.getByText('排队实例组', { exact: true })).toBeVisible()

  await page.goto('/admin/nodes')
  await expect(page.getByRole('heading', { name: '服务器节点' })).toBeVisible()
  await expect(page.getByText('Docker Desktop Linux 门禁节点', { exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '就绪' }).first()).toBeVisible()

  await page.goto('/admin/images')
  await expect(page.getByRole('heading', { name: '镜像仓库' })).toBeVisible()
  await expect(page.getByText('Python OpenSSL 门禁镜像:3.11-bookworm', { exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '已启用' }).first()).toBeVisible()

  await page.goto('/admin/network')
  await expect(page.getByRole('heading', { name: '网络隔离' })).toBeVisible()
  await expect(page.getByText('学生 → 业务数据库', { exact: true })).toBeVisible()
  await expect(page.getByText('学生 A → 学生 B', { exact: true })).toBeVisible()
  await expect(page.getByText('学生 → 判定器', { exact: true })).toBeVisible()

  await page.goto('/admin/instances')
  await expect(page.getByRole('heading', { name: '实例运维' })).toBeVisible()
  await expect(page.getByText('已销毁').first()).toBeVisible()
})
