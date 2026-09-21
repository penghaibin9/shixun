<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { classroomApi, type ApiError } from '../../app/api'
const props = defineProps<{ runtimeId: string; assist?: boolean }>()
const state = ref<'未连接'|'连接中'|'已连接'|'已断开'>('未连接')
const output = ref('')
const error = ref('')
const expiresAt = ref('')
let socket: WebSocket | null = null
const terminalElement=ref<HTMLElement|null>(null)
let resizeObserver: ResizeObserver|null=null
let reconnectTimer:ReturnType<typeof setTimeout>|null=null
let reconnectAttempts=0, connectionGeneration=0
let disposed=false
const decoder=new TextDecoder()
type TokenResponse = { token: string; websocket_path?: string; websocket_url?: string; expires_at?: string; expires_in?: number }
function websocketAddress(result: TokenResponse) {
  const target=result.websocket_url||result.websocket_path
  if(!target) throw new Error('终端连接地址缺失')
  if(/^wss?:\/\//.test(target)) return target
  const protocol=window.location.protocol==='https:'?'wss:':'ws:'
  return `${protocol}//${window.location.host}${target.startsWith('/')?'':'/'}${target}`
}
function sendResize(){
  const box=terminalElement.value?.getBoundingClientRect()
  if(!box||socket?.readyState!==WebSocket.OPEN)return
  socket.send(JSON.stringify({type:'resize',cols:Math.max(20,Math.floor(box.width/8)),rows:Math.max(8,Math.floor(box.height/18))}))
}
async function appendOutput(data:unknown){
  if(typeof data==='string'){
    try{const control=JSON.parse(data);if(control?.type==='ready'){reconnectAttempts=0;sendResize();return}}catch{/* 普通终端文本 */}
    output.value+=data
  }else if(data instanceof Blob){
    output.value+=await data.text()
  }else if(data&&typeof data==='object'&&'byteLength' in data){
    const bytes=ArrayBuffer.isView(data)
      ?new Uint8Array(data.buffer,data.byteOffset,data.byteLength)
      :new Uint8Array(data as ArrayBuffer)
    output.value+=decoder.decode(bytes,{stream:true})
  }
}
function scheduleReconnect(){
  if(disposed||reconnectAttempts>=3)return
  reconnectAttempts+=1
  reconnectTimer=setTimeout(()=>void connect(true),reconnectAttempts*500)
}
async function connect(retry=false) {
  if(!retry)reconnectAttempts=0
  if(reconnectTimer){clearTimeout(reconnectTimer);reconnectTimer=null}
  const generation=++connectionGeneration
  if(socket){socket.onclose=null;socket.close();socket=null}
  error.value=''; state.value='连接中'
  try {
    const path = props.assist ? `/api/v1/classroom/runtime/${props.runtimeId}/terminal-token` : `/api/v1/classroom/my/runtime/${props.runtimeId}/terminal-token`
    const result = await classroomApi<TokenResponse>(path, props.assist ? 'teacher' : 'student')
    if(generation!==connectionGeneration||disposed)return
    expiresAt.value=result.expires_at||(result.expires_in!=null?new Date(Date.now()+result.expires_in*1000).toISOString():'')
    const next = new WebSocket(websocketAddress(result));next.binaryType='arraybuffer';socket=next
    next.onopen=()=>{if(generation!==connectionGeneration)return;next.send(JSON.stringify({token:result.token}));state.value='已连接'}
    next.onmessage=(event)=>{if(generation===connectionGeneration)void appendOutput(event.data)}
    next.onclose=(event)=>{if(generation!==connectionGeneration||disposed)return;state.value='已断开';if(event.code===4403)error.value='终端授权已过期，请重新连接';else if(event.code===4408)error.value='终端因长时间未操作已断开，正在重连';else if(event.code===1013)error.value='终端节点暂不可用，正在重连';else if(event.code!==1000)error.value='终端连接已中断，正在重连';if(event.code!==1000&&event.code!==4403)scheduleReconnect()}
    next.onerror=()=>{if(generation===connectionGeneration)error.value='终端连接失败，正在重试'}
  } catch (caught) { const e=caught as ApiError; error.value=e.message || '终端服务暂不可用'; state.value='已断开'; scheduleReconnect() }
}
function send(value: string){ if(socket?.readyState===WebSocket.OPEN) socket.send(value) }
function onKeydown(event:KeyboardEvent){
  if(event.isComposing||event.metaKey||event.altKey)return
  const controls:Record<string,string>={Enter:'\r',Backspace:'\x7f',Tab:'\t',Escape:'\x1b',ArrowUp:'\x1b[A',ArrowDown:'\x1b[B',ArrowRight:'\x1b[C',ArrowLeft:'\x1b[D',Home:'\x1b[H',End:'\x1b[F',Delete:'\x1b[3~'}
  let value=controls[event.key]
  if(event.ctrlKey&&event.key.length===1){const code=event.key.toUpperCase().charCodeAt(0);if(code>=64&&code<=95)value=String.fromCharCode(code-64)}
  else if(!value&&event.key.length===1)value=event.key
  if(value!==undefined){event.preventDefault();send(value)}
}
watch(()=>props.runtimeId,()=>{ if(props.runtimeId)void connect() },{immediate:true})
onMounted(()=>{resizeObserver=new ResizeObserver(()=>sendResize());if(terminalElement.value)resizeObserver.observe(terminalElement.value)})
onBeforeUnmount(()=>{disposed=true;connectionGeneration+=1;if(reconnectTimer)clearTimeout(reconnectTimer);resizeObserver?.disconnect();if(socket){socket.onclose=null;socket.close()}})
</script>
<template><section class="terminal-wrap"><div class="terminal-head"><span>交互终端 · {{ state }}</span><button class="yk-button" type="button" @click="connect()">重新连接</button></div><small v-if="expiresAt" class="muted">本次连接授权有效至 {{ expiresAt }}</small><div v-if="error" class="error-panel">{{ error }}</div><div ref="terminalElement" class="terminal" tabindex="0" role="textbox" aria-label="实验终端" @keydown="onKeydown">{{ output || '正在等待终端输出…' }}</div></section></template>
