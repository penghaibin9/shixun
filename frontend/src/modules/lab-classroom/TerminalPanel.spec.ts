import { mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import TerminalPanel from './TerminalPanel.vue'

class FakeSocket {
  static OPEN=1
  static instances:FakeSocket[]=[]
  readyState=0
  sent:string[]=[]
  onopen: null|(()=>void)=null
  onmessage=null
  onclose=null
  onerror=null
  constructor(public url:string){FakeSocket.instances.push(this);queueMicrotask(()=>{this.readyState=1;this.onopen?.()})}
  close(){}
  send(value:string){this.sent.push(value)}
}

afterEach(()=>{vi.unstubAllGlobals();localStorage.clear();FakeSocket.instances=[]})

test('终端短期令牌仅留在组件内存中', async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({token:'short-lived-secret',websocket_path:'/api/v1/runtime-instances/runtime-a/terminal',expires_at:'2026-09-21T19:00:00Z'})}))
  vi.stubGlobal('WebSocket',FakeSocket)
  vi.stubGlobal('ResizeObserver',class { observe(){} disconnect(){} })
  const wrapper=mount(TerminalPanel,{props:{runtimeId:'runtime-a'}})
  await new Promise(resolve=>setTimeout(resolve,0))
  expect(wrapper.text()).toContain('已连接')
  const socket=FakeSocket.instances[0]
  expect(socket.url).toBe('ws://localhost:3000/api/v1/runtime-instances/runtime-a/terminal')
  expect(socket.url).not.toContain('token')
  expect(socket.sent[0]).toBe(JSON.stringify({token:'short-lived-secret'}))
  expect(wrapper.text()).toContain('2026-09-21T19:00:00Z')
  expect(localStorage.getItem('terminal-token')).toBeNull()
  expect([...Array(localStorage.length)].map((_,i)=>localStorage.getItem(localStorage.key(i)||''))).not.toContain('short-lived-secret')
})

test('兼容绝对连接地址和剩余有效秒数',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({token:'another-secret',websocket_url:'wss://terminal.example/ws?channel=student',expires_in:30})}))
  vi.stubGlobal('WebSocket',FakeSocket)
  vi.stubGlobal('ResizeObserver',class { observe(){} disconnect(){} })
  const wrapper=mount(TerminalPanel,{props:{runtimeId:'runtime-b'}})
  await new Promise(resolve=>setTimeout(resolve,0))
  const socket=FakeSocket.instances[0]
  expect(socket.url).toBe('wss://terminal.example/ws?channel=student')
  expect(socket.url).not.toContain('another-secret')
  expect(socket.sent[0]).toBe(JSON.stringify({token:'another-secret'}))
  expect(wrapper.text()).toContain('本次连接授权有效至')
})
