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
type TokenResponse = { token: string; websocket_path?: string; websocket_url?: string; expires_at?: string; expires_in?: number }
function websocketAddress(result: TokenResponse) {
  const target=result.websocket_url||result.websocket_path
  if(!target) throw new Error('终端连接地址缺失')
  if(/^wss?:\/\//.test(target)) return target
  const protocol=window.location.protocol==='https:'?'wss:':'ws:'
  return `${protocol}//${window.location.host}${target.startsWith('/')?'':'/'}${target}`
}
async function connect() {
  socket?.close(); error.value=''; state.value='连接中'
  try {
    const path = props.assist ? `/api/v1/classroom/runtime/${props.runtimeId}/terminal-token` : `/api/v1/classroom/my/runtime/${props.runtimeId}/terminal-token`
    const result = await classroomApi<TokenResponse>(path, props.assist ? 'teacher' : 'student')
    expiresAt.value=result.expires_at||(result.expires_in!=null?new Date(Date.now()+result.expires_in*1000).toISOString():'')
    socket = new WebSocket(websocketAddress(result))
    socket.onopen=()=>{socket?.send(JSON.stringify({token:result.token}));state.value='已连接'}
    socket.onmessage=(event)=>output.value += String(event.data)
    socket.onclose=()=>state.value='已断开'
    socket.onerror=()=>error.value='终端连接失败，请重试'
  } catch (caught) { const e=caught as ApiError; error.value=e.message || '终端服务暂不可用'; state.value='已断开' }
}
function send(value: string){ if(socket?.readyState===WebSocket.OPEN) socket.send(value) }
watch(()=>props.runtimeId,()=>{ if(props.runtimeId) connect() },{immediate:true})
onMounted(()=>{resizeObserver=new ResizeObserver(entries=>{const box=entries[0]?.contentRect;if(box&&socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'resize',cols:Math.max(20,Math.floor(box.width/8)),rows:Math.max(8,Math.floor(box.height/18))}))});if(terminalElement.value)resizeObserver.observe(terminalElement.value)})
onBeforeUnmount(()=>{resizeObserver?.disconnect();socket?.close()})
</script>
<template><section class="terminal-wrap"><div class="terminal-head"><span>交互终端 · {{ state }}</span><button class="yk-button" type="button" @click="connect">重新连接</button></div><small v-if="expiresAt" class="muted">本次连接授权有效至 {{ expiresAt }}</small><div v-if="error" class="error-panel">{{ error }}</div><div ref="terminalElement" class="terminal" tabindex="0" @keydown="send($event.key)">{{ output || '正在等待终端输出…' }}</div></section></template>
