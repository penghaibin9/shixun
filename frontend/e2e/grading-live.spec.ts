import { expect,test } from '@playwright/test'
test('真实 MySQL 无上游事实时页面返回待处理而非假成绩',async({page})=>{
 test.skip(process.env.E2E_REAL_API!=='1','仅真实后端验收时运行')
 await page.goto('/teacher-grades');await expect(page.getByRole('heading',{name:'成绩管理'})).toBeVisible();await expect(page.getByText('等待 A/D/E 上游教学事实')).toBeVisible()
 await page.getByRole('link',{name:'我的成绩'}).click();await expect(page.getByText('待处理')).toBeVisible();await expect(page.getByText('尚待上游事实')).toBeVisible()
})
