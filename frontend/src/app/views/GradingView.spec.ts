import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, expect, it, vi } from 'vitest'
import GradingView from './GradingView.vue'

afterEach(()=>vi.restoreAllMocks())
it('学习摘要缺少上游事实时明确显示待处理',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({course_id:'course_data_security',student_id:'student_1',status:'PENDING',grade:{status:'PENDING',items:[]},risk:{status:'PENDING',items:[]},analytics:{status:'PENDING'},missing_upstream:['上游班级成员/完整教学事实或成绩入账尚未就绪']}),{status:200,headers:{'Content-Type':'application/json'}})))
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/student-score',component:GradingView,meta:{page:'student'}}]});await router.push('/student-score');await router.isReady()
  const wrapper=mount(GradingView,{global:{plugins:[router]}});await flushPromises()
  expect(wrapper.text()).toContain('待处理');expect(wrapper.text()).toContain('尚待上游事实');expect(wrapper.text()).toContain('上游班级成员')
})

it('成绩追溯明确展示人工调整且不伪装为权重',async()=>{
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
    const url=String(input)
    const body=url.includes('/grading/policies/')
      ? {status:'PUBLISHED',version_no:1,items:[{component:'ATTENDANCE',weight_percent:10}]}
      : url.includes('/trace/')
        ? {status:'READY',student_id:'student_1',total_score:95,policy_version:1,components:[{component:'MANUAL_ADJUSTMENT',score:5,weight_percent:null,weighted_score:5,sources:[{event_id:'event_1',source_type:'MANUAL_ADJUSTMENT',source_id:'manual_bonus',normalized_score:5,occurred_at:'2026-09-22T10:00:00Z'}]}]}
        : {status:'READY',policy_version:1,items:[{student_id:'student_1',total_score:95,completeness:'READY'}]}
    return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}})
  }))
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/teacher-grades',component:GradingView,meta:{page:'grades'}}]});await router.push('/teacher-grades');await router.isReady()
  const wrapper=mount(GradingView,{global:{plugins:[router]}});await flushPromises();await wrapper.get('tbody button').trigger('click');await flushPromises()
  expect(wrapper.text()).toContain('人工调整');expect(wrapper.text()).toContain('+5 分');expect(wrapper.text()).not.toContain('人工调整 null%')
})
