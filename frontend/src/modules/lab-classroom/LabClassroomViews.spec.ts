import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import StudentLabView from './StudentLabView.vue'
import TeacherLogsView from './TeacherLogsView.vue'

afterEach(()=>{vi.unstubAllGlobals();localStorage.clear()})

test('日志中心按所选班级和实验发布查询并从真实名单选择分发目标',async()=>{
  localStorage.setItem('yk-course-id','course-a')
  localStorage.setItem('yk-class-id','class-a')
  localStorage.setItem('yk-release-id','release-1')
  const requests:Array<{url:string;method:string;body?:string}>=[]
  vi.stubGlobal('fetch',vi.fn(async(input:string|URL|Request,init:RequestInit={})=>{
    const url=String(input), method=init.method||'GET'
    requests.push({url,method,body:init.body as string|undefined})
    const body=url.includes('/teaching-logs/audit')
      ?{items:[{event_id:'event-1',event_type:'runtime.command',student_id:'student-a',occurred_at:'2026-09-22T10:00:00'}]}
      :url.includes('/classroom/lab-releases/')
        ?{items:[{student_id:'student-a',student_name:'张同学',student_no:'2026001'}]}
        :method==='POST'
          ?{distribution_id:'distribution-1',status:'ASSIGNED'}
          :{items:[],total:0}
    return {ok:true,json:async()=>body} as Response
  }))
  const wrapper=mount(TeacherLogsView)
  await flushPromises()
  expect(requests.some(request=>request.url.includes('/teaching-logs/audit?class_id=class-a&lab_release_id=release-1'))).toBe(true)
  await wrapper.get('[role="checkbox"]').trigger('click')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  const created=requests.find(request=>request.method==='POST')
  expect(created).toBeTruthy()
  expect(JSON.parse(created?.body||'{}').target_student_ids).toEqual(['student-a'])
  expect(wrapper.text()).toContain('日志任务已分发给 1 名学生')
  wrapper.unmount()
})

test('学生实验失败状态使用中文并只提供重新启动',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({status:'FAILED',current_step:2,total_steps:6,raw_score:20,max_score:100})}))
  const wrapper=mount(StudentLabView)
  await flushPromises()
  expect(wrapper.text()).toContain('失败，可重试')
  expect(wrapper.get('button.primary').text()).toBe('重新启动')
  expect(wrapper.text()).not.toContain('FAILED')
  wrapper.unmount()
})
