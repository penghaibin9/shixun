import { mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import TerminalPanel from './TerminalPanel.vue'

class FakeSocket {
  static OPEN=1
  readyState=1
  onopen: null|(()=>void)=null
  onmessage=null
  onclose=null
  onerror=null
  constructor(public url:string){queueMicrotask(()=>this.onopen?.())}
  close(){}
  send(){}
}

afterEach(()=>{vi.unstubAllGlobals();localStorage.clear()})

test('终端短期令牌仅留在组件内存中', async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({token:'short-lived-secret',websocket_url:'ws://example.test/terminal'})}))
  vi.stubGlobal('WebSocket',FakeSocket)
  vi.stubGlobal('ResizeObserver',class { observe(){} disconnect(){} })
  const wrapper=mount(TerminalPanel,{props:{runtimeId:'runtime-a'}})
  await new Promise(resolve=>setTimeout(resolve,0))
  expect(wrapper.text()).toContain('已连接')
  expect(localStorage.getItem('terminal-token')).toBeNull()
  expect([...Array(localStorage.length)].map((_,i)=>localStorage.key(i))).not.toContain('short-lived-secret')
})
