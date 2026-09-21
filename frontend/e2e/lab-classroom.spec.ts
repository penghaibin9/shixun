import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  const statuses=[...Array(10).fill('SUBMITTED'),...Array(18).fill('RUNNING'),...Array(2).fill('FAILED'),...Array(13).fill('NOT_STARTED')]
  const students=statuses.map((status,index)=>({student_id:`student-${index+1}`,student_name:`学生${index+1}`,student_no:`2026${String(index+1).padStart(3,'0')}`,status,current_step:status==='NOT_STARTED'?0:3,total_steps:6,raw_score:status==='NOT_STARTED'?0:40,max_score:100,runtime_instance_id:status==='NOT_STARTED'?null:`runtime-${index+1}`}))
  await page.route('**/api/v1/**', async route => {
    const url=new URL(route.request().url()), path=url.pathname, method=route.request().method()
    const reply=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)})
    if(path.endsWith('/summary')) return reply({lab_release_id:'release-1',class_id:'class-a',started:30,completed:10,running:18,failed:2,not_started:13})
    if(path.endsWith('/students')) return reply({items:students,total:43})
    if(path==='/api/v1/teaching-logs/audit') return reply({items:[{artifact_id:'audit-1',name:'操作审计.log',student_id:'student-1'}]})
    if(path==='/api/v1/teaching-logs/traffic') return reply({items:[{artifact_id:'traffic-1',name:'流量样本.pcap',student_id:'student-1'}]})
    if(path==='/api/v1/teaching-logs/distributions'&&method==='GET') return reply({items:[],total:0})
    if(path==='/api/v1/teaching-logs/distributions'&&method==='POST') return reply({distribution_id:'dist-1',status:'ASSIGNED'},201)
    if(path==='/api/v1/teaching-logs/my-assignments') return reply({items:[{assignment_id:'assignment-1',status:'ASSIGNED',assigned_at:'2026-09-21',distribution:{title:'流量分析任务',instruction:'定位异常连接',distribution_type:'TRAFFIC'}}]})
    if(path.includes('/my-assignments/')&&path.endsWith('/download')) return reply({download_url:'about:blank',expires_in:60})
    if(path==='/api/v1/classroom/my/lab-releases/release-1') return reply({status:'RUNNING',runtime_instance_id:'runtime-1',current_step:3,total_steps:6,raw_score:40,max_score:100,steps:[{title:'识别服务',status:'已通过'}]})
    if(path.endsWith('/terminal-token')) return reply({token:'short-lived',websocket_url:'ws://127.0.0.1:9/terminal'})
    return reply({status:'ACCEPTED'})
  })
})

test('教师可查看 43 人课堂、执行操作并分发日志', async ({page})=>{
  await page.goto('/lab-live')
  await expect(page.getByText('共 43 名学生')).toBeVisible()
  await expect(page.getByText('18',{exact:true})).toBeVisible()
  await page.getByRole('button',{name:'查看'}).first().click()
  await page.getByRole('tab',{name:'课堂处置'}).click()
  await page.getByRole('button',{name:'提醒',exact:true}).click()
  await page.getByRole('button',{name:'关闭'}).click()
  await page.getByRole('link',{name:'教学日志'}).click()
  await page.getByRole('button',{name:'确认分发'}).click()
  await expect(page.getByText('日志任务已分发')).toBeVisible()
})

test('学生可查看实验步骤与本人日志任务', async ({page})=>{
  await page.goto('/student-lab')
  await expect(page.getByRole('heading',{name:'我的实验'})).toBeVisible()
  await expect(page.getByText('识别服务')).toBeVisible()
  await page.getByRole('link',{name:'我的日志任务'}).click()
  await expect(page.getByText('流量分析任务')).toBeVisible()
  await expect(page.getByRole('button',{name:'下载日志包'})).toBeVisible()
})
