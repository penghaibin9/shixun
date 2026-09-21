<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { classroomApi, type ApiError } from '../../app/api'
import TerminalPanel from './TerminalPanel.vue'
type Lab={status:string;runtime_instance_id?:string;current_step?:number;total_steps?:number;raw_score?:number;max_score?:number;steps?:any[]}
const release=localStorage.getItem('yk-release-id')||'release-1', lab=ref<Lab|null>(null), error=ref(''), message=ref(''), loading=ref(true)
async function load(){loading.value=true;error.value='';try{lab.value=await classroomApi<Lab>(`/api/v1/classroom/my/lab-releases/${release}`,'student')}catch(e){error.value=(e as ApiError).message}finally{loading.value=false}}
async function start(){try{lab.value=await classroomApi<Lab>(`/api/v1/classroom/my/lab-releases/${release}/start`,'student',{method:'POST'});message.value='实验实例正在准备';await load()}catch(e){error.value=(e as ApiError).message}}
async function submit(){if(!confirm('提交后将进入判定流程，确定提交？'))return;try{await classroomApi(`/api/v1/classroom/my/lab-releases/${release}/submit`,'student',{method:'POST'});message.value='实验已提交';await load()}catch(e){error.value=(e as ApiError).message}}
onMounted(load)
</script>
<template><div class="stack"><header class="page-header"><div><h1>我的实验</h1><p>按步骤完成实验，系统会实时记录进度与检查点。</p></div><button class="yk-button" @click="load">刷新</button></header><div v-if="loading" class="card">正在加载实验…</div><div v-if="error" class="pending-panel"><b>实验运行服务待就绪</b><div>{{error}}</div><button class="yk-button" @click="load">重试</button></div><p v-if="message" class="status done">{{message}}</p><template v-if="lab"><section class="grid grid-4"><div class="card kpi">状态<b>{{lab.status}}</b></div><div class="card kpi">步骤<b>{{lab.current_step||0}} / {{lab.total_steps||0}}</b></div><div class="card kpi">得分<b>{{lab.raw_score||0}} / {{lab.max_score||100}}</b></div><div class="card"><button v-if="lab.status==='NOT_STARTED'" class="yk-button primary" @click="start">启动实验</button><button v-else class="yk-button primary" @click="submit">提交实验</button></div></section><section class="card"><h3>实验步骤</h3><ol v-if="lab.steps?.length"><li v-for="(step,index) in lab.steps" :key="index">{{step.title||`步骤 ${index+1}`}} · {{step.status||'待完成'}}</li></ol><p v-else class="muted">步骤数据待运行服务返回。</p></section><TerminalPanel v-if="lab.runtime_instance_id" :runtime-id="lab.runtime_instance_id"/></template></div></template>
