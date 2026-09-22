<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { classroomApi, type ApiError } from '../../app/api'
import TerminalPanel from './TerminalPanel.vue'
type Lab={status:string;runtime_instance_id?:string;current_step?:number;total_steps?:number;raw_score?:number;max_score?:number;steps?:any[]}
const release=localStorage.getItem('yk-release-id')||'release-1', lab=ref<Lab|null>(null), error=ref(''), message=ref(''), loading=ref(true)
let refreshTimer:ReturnType<typeof setInterval>|null=null
const statusLabel=computed(()=>({NOT_STARTED:'可启动',QUEUED:'排队中',SCHEDULING:'正在调度',STARTING:'启动中',RUNNING:'运行中',SUBMITTED:'已提交',COMPLETED:'已完成',DESTROYED:'已关闭',FAILED:'失败，可重试'}[lab.value?.status||'NOT_STARTED']||'状态待确认'))
const canStart=computed(()=>['NOT_STARTED','FAILED','DESTROYED'].includes(lab.value?.status||'NOT_STARTED'))
const canSubmit=computed(()=>lab.value?.status==='RUNNING')
async function load(){loading.value=true;error.value='';try{lab.value=await classroomApi<Lab>(`/api/v1/classroom/my/lab-releases/${release}`,'student')}catch(e){error.value=(e as ApiError).message}finally{loading.value=false}}
async function start(){try{lab.value=await classroomApi<Lab>(`/api/v1/classroom/my/lab-releases/${release}/start`,'student',{method:'POST'});message.value='实验实例正在准备';await load()}catch(e){error.value=(e as ApiError).message}}
async function submit(){if(!confirm('提交后将进入判定流程，确定提交？'))return;try{await classroomApi(`/api/v1/classroom/my/lab-releases/${release}/submit`,'student',{method:'POST'});message.value='实验已提交';await load()}catch(e){error.value=(e as ApiError).message}}
onMounted(()=>{void load();refreshTimer=setInterval(()=>void load(),3000)})
onBeforeUnmount(()=>{if(refreshTimer)clearInterval(refreshTimer)})
</script>
<template><div class="stack"><header class="page-header"><div><h1>我的实验</h1><p>按步骤完成实验，系统会实时记录进度与检查点。</p></div><button class="yk-button" @click="load">刷新</button></header><div v-if="loading&&!lab" class="card">正在加载实验…</div><div v-if="error" class="pending-panel"><b>实验运行服务待就绪</b><div>{{error}}</div><button class="yk-button" @click="load">重试</button></div><p v-if="message" class="status done">{{message}}</p><template v-if="lab"><section class="grid grid-4"><div class="card kpi">状态<b>{{statusLabel}}</b></div><div class="card kpi">步骤<b>{{lab.current_step||0}} / {{lab.total_steps||0}}</b></div><div class="card kpi">得分<b>{{lab.raw_score||0}} / {{lab.max_score||100}}</b></div><div class="card actions"><button v-if="canStart" class="yk-button primary" @click="start">{{lab.status==='FAILED'?'重新启动':'启动实验'}}</button><button v-if="canSubmit" class="yk-button primary" @click="submit">提交实验</button><span v-if="!canStart&&!canSubmit" class="muted">{{statusLabel}}</span></div></section><section class="card"><h3>实验步骤</h3><ol v-if="lab.steps?.length"><li v-for="(step,index) in lab.steps" :key="index">{{step.title||`步骤 ${index+1}`}} · {{step.status||'待完成'}}</li></ol><p v-else class="muted">步骤数据待运行服务返回。</p></section><TerminalPanel v-if="lab.runtime_instance_id&&lab.status==='RUNNING'" :runtime-id="lab.runtime_instance_id"/><div v-else-if="!canStart" class="pending-panel">终端将在实验环境进入运行状态后开放。</div></template></div></template>
