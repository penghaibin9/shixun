import {flushPromises,mount} from '@vue/test-utils'
import {beforeEach,describe,expect,it,vi} from 'vitest'
import TeacherStudentsView from './TeacherStudentsView.vue'

vi.mock('vue-router',()=>({RouterLink:{template:'<a><slot /></a>'}}))

describe('教师学生管理',()=>{
  beforeEach(()=>{localStorage.clear();localStorage.setItem('yk-class-id','class-a')})
  it('跨班拒绝时显示明确无权限状态',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,json:async()=>({code:'AUTH.SCOPE_DENIED',message:'不能访问该班级',request_id:'req-test',details:{}})}))
    const wrapper=mount(TeacherStudentsView,{global:{stubs:{RouterLink:{template:'<a><slot /></a>'}}}})
    await flushPromises()
    expect(wrapper.text()).toContain('无权限查看该班级')
    vi.unstubAllGlobals()
  })
})
