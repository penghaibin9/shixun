import { mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import TerminalPanel from './TerminalPanel.vue'

class FakeSocket {
  static OPEN=1
  static instances:FakeSocket[]=[]
  readyState=0
  binaryType='blob'
  sent:string[]=[]
  onopen: null|(()=>void)=null
  onmessage:null|((event:{data:unknown})=>void)=null
  onclose:null|((event:{code:number})=>void)=null
  onerror:null|(()=>void)=null
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

test('解码二进制输出并把常用按键转换为终端控制字符',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({token:'keyboard-secret',websocket_path:'/terminal'})}))
  vi.stubGlobal('WebSocket',FakeSocket)
  vi.stubGlobal('ResizeObserver',class { observe(){} disconnect(){} })
  const wrapper=mount(TerminalPanel,{props:{runtimeId:'runtime-c'}})
  await new Promise(resolve=>setTimeout(resolve,0))
  const socket=FakeSocket.instances[0]
  socket.onmessage?.({data:new TextEncoder().encode('真实输出').buffer})
  await new Promise(resolve=>setTimeout(resolve,0))
  expect(wrapper.text()).toContain('真实输出')
  const terminal=wrapper.get('[aria-label="实验终端"]')
  await terminal.trigger('keydown',{key:'Enter'})
  await terminal.trigger('keydown',{key:'Backspace'})
  await terminal.trigger('keydown',{key:'ArrowUp'})
  await terminal.trigger('keydown',{key:'c',ctrlKey:true})
  expect(socket.sent.slice(1)).toEqual(['\r','\x7f','\x1b[A','\x03'])
})
