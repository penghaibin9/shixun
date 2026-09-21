<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import YkPageHeader from '../../components/common/YkPageHeader.vue'
import YkDataTable from '../../components/common/YkDataTable.vue'
import { runtimeEvents, runtimeImages, runtimeInstances, runtimeNodes, runtimeOverview, runtimeQueue, type ApiError, type RuntimeEvent, type RuntimeImage, type RuntimeInstanceSummary, type RuntimeNode, type RuntimeOverview, type RuntimeQueueItem } from '../api'

const route = useRoute()
const loading = ref(true)
const error = ref('')
const overview = ref<RuntimeOverview>({ nodes_ready: 0, running_instances: 0, failed_instances: 0, destroyed_instances: 0, queued_groups: 0 })
const nodes = ref<RuntimeNode[]>([])
const images = ref<RuntimeImage[]>([])
const instances = ref<RuntimeInstanceSummary[]>([])
const queue = ref<RuntimeQueueItem[]>([])
const events = ref<RuntimeEvent[]>([])
const section = computed(() => route.path.split('/').pop() || 'overview')
const page = computed(() => ({
  overview: ['运行总览', '节点、实例、队列和异常均来自运行时事实库。'],
  nodes: ['服务器节点', '查看节点健康、可用资源、镜像缓存和调度状态。'],
  images: ['镜像仓库', '仅通过扫描、启动自检和教学验证的固定摘要镜像可启用。'],
  scheduler: ['调度与队列', '调度决策记录节点、分数、原因和时间，容量不足时明确排队。'],
  network: ['网络隔离', '每个学生实例组独立网络，默认禁止业务数据库、其他学生和外网。'],
  instances: ['实例运维', '查看真实实例状态、所在节点、开始时间和回收期限。'],
  alerts: ['告警中心', '运行失败、节点异常和资源问题由运行事件生成。'],
  recovery: ['异常恢复', '重建保留检查点事实，销毁幂等并清理容器与网络。'],
}[section.value] || ['实验基础设施', '运行底座事实。']))

const nodeRows = computed(() => nodes.value.map(x => ({ name: x.name, state: x.scheduling_paused ? '暂停调度' : x.status === 'READY' ? '就绪' : '异常', cpu: x.capacity ? `${x.capacity.cpu_available.toFixed(1)} / ${x.cpu_total.toFixed(1)} 核可用` : '无心跳', memory: x.capacity ? `${x.capacity.memory_available_mb} / ${x.memory_total_mb} MB 可用` : '无心跳', groups: x.capacity?.running_groups ?? 0, weight: x.weight })))
const imageRows = computed(() => images.value.map(x => ({ name: `${x.name}:${x.tag}`, digest: `${x.digest.slice(0, 19)}…`, scan: status(x.scan_status), startup: status(x.startup_check_status), teaching: status(x.teaching_validation_status), enabled: x.enabled ? '已启用' : '未启用' })))
const instanceRows = computed(() => instances.value.map(x => ({ id: x.runtime_instance_id, student: x.student_id || '教师预演', lab: x.lab_version_id, node: x.node_id, role: x.node_key, state: status(x.status), expires: new Date(x.expires_at).toLocaleString('zh-CN') })))
const queueRows = computed(() => queue.value.map(x => ({ id: x.runtime_request_id, student: x.student_id || '教师预演', priority: x.priority, attempts: x.attempts, reason: x.reason || '等待调度', time: new Date(x.enqueued_at).toLocaleString('zh-CN') })))
const eventRows = computed(() => events.value.map(x => ({ type: eventName(x.event_type), instance: x.runtime_instance_id || '系统', time: new Date(x.occurred_at).toLocaleString('zh-CN') })))

function status(value: string) { return ({ PASSED: '通过', FAILED: '失败', PENDING: '待验证', CREATED: '已创建', QUEUED: '排队中', SCHEDULING: '调度中', STARTING: '启动中', RUNNING: '运行中', STOPPING: '停止中', DESTROYED: '已销毁', CANCELED: '已取消', READY: '就绪' } as Record<string, string>)[value] || '未知状态' }
function eventName(value: string) { return ({ 'runtime.request.created': '运行请求已创建', 'runtime.request.queued': '运行请求已排队', 'runtime.group.scheduled': '实例组已调度', 'lab.instance.started': '实例已启动', 'lab.instance.failed': '实例启动失败', 'lab.instance.destroyed': '实例已销毁', 'lab.checkpoint.passed': '检查点通过', 'lab.checkpoint.failed': '检查点未通过', 'lab.submitted': '实验已提交' } as Record<string, string>)[value] || '运行事件' }
async function load() { loading.value = true; error.value = ''; try { [overview.value, nodes.value, images.value, instances.value, queue.value, events.value] = await Promise.all([runtimeOverview(), runtimeNodes(), runtimeImages(), runtimeInstances(), runtimeQueue(), runtimeEvents()]) } catch (reason) { error.value = (reason as ApiError).message } finally { loading.value = false } }
onMounted(load)
watch(() => route.path, load)
</script>

<template>
  <YkPageHeader :title="page[0]" :description="page[1]"><template #actions><button class="yk-button" @click="load">刷新事实</button></template></YkPageHeader>
  <div v-if="loading" class="card state-card">正在读取运行时事实…</div>
  <div v-else-if="error" class="card state-card error-state">{{ error }}</div>
  <template v-else>
    <div v-if="section === 'overview'" class="grid grid-4">
      <article class="card kpi"><span class="muted">就绪节点</span><b>{{ overview.nodes_ready }}</b></article>
      <article class="card kpi"><span class="muted">运行实例</span><b>{{ overview.running_instances }}</b></article>
      <article class="card kpi"><span class="muted">排队实例组</span><b>{{ overview.queued_groups }}</b></article>
      <article class="card kpi"><span class="muted">异常实例</span><b>{{ overview.failed_instances }}</b></article>
    </div>
    <section v-if="section === 'overview'" class="card runtime-section"><h2>当前运行关注</h2><YkDataTable :columns="[{key:'type',label:'事件'},{key:'instance',label:'实例'},{key:'time',label:'时间'}]" :rows="eventRows.slice(0,8)" /></section>
    <section v-if="section === 'nodes'" class="card"><YkDataTable :columns="[{key:'name',label:'节点'},{key:'state',label:'状态'},{key:'cpu',label:'处理器'},{key:'memory',label:'内存'},{key:'groups',label:'实例组'},{key:'weight',label:'调度权重'}]" :rows="nodeRows" /></section>
    <section v-if="section === 'images'" class="card"><YkDataTable :columns="[{key:'name',label:'镜像'},{key:'digest',label:'固定摘要'},{key:'scan',label:'漏洞扫描'},{key:'startup',label:'启动自检'},{key:'teaching',label:'教学验证'},{key:'enabled',label:'可用状态'}]" :rows="imageRows" /></section>
    <section v-if="section === 'scheduler'" class="grid grid-2"><div class="card"><h2>等待队列</h2><YkDataTable :columns="[{key:'student',label:'学生'},{key:'priority',label:'优先级'},{key:'attempts',label:'尝试'},{key:'reason',label:'原因'}]" :rows="queueRows" /></div><div class="card"><h2>调度决策时间线</h2><YkDataTable :columns="[{key:'type',label:'事件'},{key:'instance',label:'实例'},{key:'time',label:'时间'}]" :rows="eventRows" /></div></section>
    <section v-if="section === 'network'" class="grid grid-3"><article class="card policy-card"><b>学生 → 业务数据库</b><span class="badge success">默认拒绝</span><p>实验网络采用内部网络，不发布业务端口。</p></article><article class="card policy-card"><b>学生 A → 学生 B</b><span class="badge success">默认拒绝</span><p>每个实例组使用独立网络。</p></article><article class="card policy-card"><b>学生 → 判定器</b><span class="badge success">组内允许</span><p>仅允许同实例组受控判定通信。</p></article></section>
    <section v-if="section === 'instances'" class="card"><YkDataTable :columns="[{key:'student',label:'学生'},{key:'lab',label:'实验版本'},{key:'node',label:'计算节点'},{key:'role',label:'容器角色'},{key:'state',label:'状态'},{key:'expires',label:'回收时间'}]" :rows="instanceRows" /></section>
    <section v-if="section === 'alerts'" class="card"><YkDataTable :columns="[{key:'type',label:'告警/事件'},{key:'instance',label:'来源实例'},{key:'time',label:'发生时间'}]" :rows="eventRows.filter(x => x.type.includes('失败') || x.type.includes('排队'))" /></section>
    <section v-if="section === 'recovery'" class="grid grid-3"><article class="card recovery-card"><h2>实例启动失败</h2><p>记录失败原因，回滚已创建容器与网络，并进入受控重试。</p></article><article class="card recovery-card"><h2>节点离线</h2><p>停止新调度；运行请求可在健康节点重建。</p></article><article class="card recovery-card"><h2>超时回收</h2><p>先保留检查点、事件与制品事实，再销毁容器和网络。</p></article></section>
  </template>
</template>

<style scoped>
.runtime-section{margin-top:14px}.runtime-section h2,.card h2{font-size:16px;margin:0 0 14px}.policy-card{display:grid;gap:12px}.policy-card p,.recovery-card p{color:var(--muted);line-height:1.65;margin:0}
</style>
