import { expect,test } from '@playwright/test'

const policy={course_id:'course_data_security',version_no:1,status:'PUBLISHED',items:[{component:'ATTENDANCE',weight_percent:10},{component:'ASSIGNMENT',weight_percent:20},{component:'QUIZ',weight_percent:20},{component:'LAB',weight_percent:40},{component:'INTERACTION',weight_percent:10}]}
const book={gradebook_id:'gb1',course_id:'course_data_security',class_id:'class_2301',policy_version:1,status:'READY',items:[{student_id:'student_1',total_score:91,completeness:'READY'},{student_id:'student_2',total_score:68,completeness:'READY'}]}
const overview={status:'READY',avg_assignment:70,avg_quiz:80,attendance_rate:75,course_average:79.5,ranking:[{student_id:'student_1',total_score:91}]}
const section={status:'READY',lesson_id:'lesson_3_2',average:78,distribution:{'0-59':0,'60-69':1,'70-79':0,'80-89':0,'90-100':1},ranking:[]}
const trace={status:'READY',student_id:'student_1',total_score:91,policy_version:1,components:[{component:'LAB',score:100,weight_percent:40,weighted_score:40,sources:[{event_id:'e1',source_type:'LAB_SUBMISSION',source_id:'lab_rsa',normalized_score:100,occurred_at:'2026-09-21T12:00:00Z'}]}]}

test.beforeEach(async({page})=>{
 await page.route('**/api/v1/**',async route=>{const url=route.request().url(),method=route.request().method();let body:any={}
  if(url.includes('/grading/policies/'))body=policy
  else if(url.includes('/trace/'))body=trace
  else if(url.includes('/gradebook/courses/')&&url.includes('/students/'))body={...book,status:'POSTED',items:[book.items[0]]}
  else if(url.includes('/gradebook/courses/'))body=book
  else if(url.includes('/recalculate'))body=book
  else if(url.endsWith('/post'))body={...book,status:'POSTED'}
  else if(url.includes('/overview'))body=overview
  else if(url.includes('/sections/'))body=section
  else if(url.includes('/labs/by-student'))body={status:'READY',items:[{student_id:'student_1',sum_lab_score:100,submitted_count:1,unsubmitted_count:0}]}
  else if(url.includes('/labs/by-lab'))body={status:'READY',items:[{lab_release_id:'lab_rsa',avg_score:90,submitted_students:2,unsubmitted_students:0}]}
  else if(url.includes('/learning-summary'))body={status:'READY',grade:{...book,status:'POSTED',items:[book.items[0]]},risk:{status:'READY',items:[]},analytics:overview,missing_upstream:[]}
  else if(url.includes('/precheck'))body={status:'READY',blocking:0,blocking_items:[],checks:{roster_frozen:true,gradebook_posted:true,grade_event_traceable:true,lab_evidence_referenced:true,resources_frozen:true}}
  else if(url.includes('/freeze'))body={course_id:'course_data_security',artifacts:[{type:'GRADEBOOK_XLSX'}]}
  else if(url.includes('/archives/courses/'))body={status:'PENDING'}
  else if(url.includes('/audit/events'))body={items:[{audit_event_id:'a1',occurred_at:'2026-09-21T12:00:00Z',actor_user_id:'teacher_f',actor_role:'teacher',action:'GRADEBOOK_POSTED',resource_type:'gradebook',resource_id:'gb1',result:'SUCCESS',reason:null}],total:1}
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)})
 })
 page.on('dialog',dialog=>dialog.accept())
})

test('成绩到归档再到学生成绩的浏览器主链',async({page})=>{
 await page.goto('/teacher-grades');await expect(page.getByRole('heading',{name:'成绩管理'})).toBeVisible()
 await page.getByRole('button',{name:'重新计算'}).click();await page.getByRole('button',{name:'追溯'}).first().click();await expect(page.getByText('成绩来源追溯')).toBeVisible()
 await page.getByRole('button',{name:'确认成绩入账'}).click()
 await page.getByRole('link',{name:'学情分析'}).click();await expect(page.getByText('79.5')).toBeVisible();await page.getByRole('button',{name:'② 按小节'}).click();await expect(page.getByText('平均成绩：78')).toBeVisible();await page.getByRole('button',{name:'③ 实验维度'}).click();await expect(page.getByText('lab_rsa')).toBeVisible()
 await page.getByRole('link',{name:'课程归档'}).click();await page.getByRole('button',{name:'归档预检'}).click();await expect(page.getByText('成绩已入账')).toBeVisible();await page.getByRole('button',{name:'冻结归档'}).click()
 await page.getByRole('link',{name:'我的成绩'}).click();await expect(page.getByRole('heading',{name:'我的成绩'})).toBeVisible();await expect(page.getByText('91')).toBeVisible()
 await page.getByRole('link',{name:'审计日志'}).click();await expect(page.getByText('成绩已入账')).toBeVisible()
})
