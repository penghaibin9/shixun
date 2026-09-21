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
