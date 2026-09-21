<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import YkCheck from '../../components/common/YkCheck.vue'
import YkPageHeader from '../../components/common/YkPageHeader.vue'
import YkSelect from '../../components/common/YkSelect.vue'
import { cloneVersion, createRelease, exportVersion, listLabs, preflightRelease, publishVersion, saveVersion, teacherPreview, validateVersion, type ApiError, type Lab, type LabRelease, type LabVersion } from '../api'

const route = useRoute()
const lab = ref<Lab | null>(null)
const version = ref<LabVersion | null>(null)
const release = ref<LabRelease | null>(null)
const step = ref(1)
const loading = ref(true)
const busy = ref(false)
const message = ref('')
const error = ref('')
const selectedClass = ref(true)
const category = ref('crypto')
const steps = [
  ['基本信息', '目标、模板、时长、总分'], ['场景拓扑', '主机、网络、资源限制'], ['Docker 镜像', '运行配置与安全约束'],
  ['DAG 与判分', '步骤、依赖、得分点'], ['发布范围', '班级、时间、尝试次数'], ['教师预演', '完整跑通再发布'],
]
const categories = [{ label: '密码学', value: 'crypto' }, { label: '访问控制', value: 'access' }, { label: '日志审计', value: 'audit' }]
const score = computed(() => version.value?.spec.checkpoints.reduce((sum, item) => sum + item.score, 0) ?? 0)
const editable = computed(() => version.value?.status !== 'PUBLISHED')

onMounted(async () => {
  try {
    const labs = await listLabs()
    lab.value = labs.find(item => item.lab_definition_id === String(route.query.lab ?? 'lab_rsa')) ?? labs[0] ?? null
    version.value = lab.value?.latest_version ?? null
  } catch (reason) { error.value = (reason as ApiError).message }
  finally { loading.value = false }
})

async function createDraft() {
  if (!lab.value) return
  await act(async () => { version.value = await cloneVersion(lab.value!.lab_definition_id); message.value = `已创建 V${version.value.version} 草稿，原发布版本保持不变。` })
}

async function saveTopology(event: DragEvent, nodeIndex: number) {
  if (!version.value || !editable.value) return
  const canvas = event.currentTarget instanceof HTMLElement ? event.currentTarget.parentElement : null
  if (!canvas) return
  const bounds = canvas.getBoundingClientRect()
  version.value.spec.nodes[nodeIndex].position_x = Math.max(0, Math.round(event.clientX - bounds.left - 60))
  version.value.spec.nodes[nodeIndex].position_y = Math.max(0, Math.round(event.clientY - bounds.top - 24))
  await act(async () => { version.value = await saveVersion(version.value!); message.value = '拓扑坐标已保存到数据库。' })
}

async function runValidation() { if (version.value) await act(async () => { version.value = await validateVersion(version.value!.lab_version_id); message.value = '发布门禁通过：拓扑、镜像摘要、DAG 和总分均有效。' }) }
async function freezeVersion() { if (version.value) await act(async () => { version.value = await publishVersion(version.value!.lab_version_id); message.value = `V${version.value.version} 已发布并冻结。` }) }
async function prepareRelease() {
  if (!version.value) return
  await act(async () => { release.value = await createRelease(version.value!.lab_version_id); const result = await preflightRelease(release.value.lab_release_id); message.value = result.passed ? '发布范围预检通过。' : '发布范围预检未通过。' })
}
async function preview() {
  if (!release.value) return
  await act(async () => { const result = await teacherPreview(release.value!.lab_release_id); message.value = `运行服务已受理预演请求：${result.runtime_request_id}` })
}
async function downloadJson() {
  if (!version.value) return
  await act(async () => {
    const blob = await exportVersion(version.value!.lab_version_id)
    const url = URL.createObjectURL(blob); const anchor = document.createElement('a')
    anchor.href = url; anchor.download = `${version.value!.lab_definition_id}-v${version.value!.version}.json`; anchor.click(); URL.revokeObjectURL(url)
    message.value = '实验定义 JSON（数据文本）已导出。'
  })
}
async function act(callback: () => Promise<void>) {
  busy.value = true; error.value = ''
  try { await callback() } catch (reason) { const apiError = reason as ApiError; error.value = `${apiError.message}${apiError.code === 'LAB.RUNTIME_PROVIDER_UNAVAILABLE' ? '（D 线运行底座尚未就绪，未伪造成功）' : ''}` }
  finally { busy.value = false }
}
</script>

<template>
  <YkPageHeader title="创建实验 · 完整 6 步设计器" description="模板 → 场景拓扑 → 镜像 → DAG 与判分 → 发布策略 → 教师预演。">
    <template #actions><div class="row"><button class="yk-button" :disabled="!version || busy" @click="downloadJson">导出实验配置</button><button class="yk-button primary" :disabled="!version || busy || version.status === 'PUBLISHED'" @click="runValidation">发布前检查</button></div></template>
  </YkPageHeader>
  <div v-if="loading" class="card state-card">正在从数据库读取 RSA 实验…</div>
  <div v-else-if="!version" class="card state-card error-state">{{ error || '没有可编辑的实验定义。' }}</div>
  <template v-else>
    <div v-if="message" class="notice success-notice">{{ message }}</div><div v-if="error" class="notice error-state">{{ error }}</div>
    <div class="builder-layout">
      <aside class="card builder-steps"><button v-for="(item, index) in steps" :key="item[0]" :class="{ active: step === index + 1 }" @click="step = index + 1"><span>{{ index + 1 }}</span><b>{{ item[0] }}</b><small>{{ item[1] }}</small></button></aside>
      <main class="card builder-workspace">
        <div class="section-title"><div><h2>{{ step }}. {{ steps[step - 1][0] }}</h2><small class="muted">{{ version.spec.name }}</small></div><span class="badge" :class="version.status === 'PUBLISHED' ? 'success' : ''">V{{ version.version }} · {{ version.status === 'PUBLISHED' ? '已发布' : version.status === 'READY' ? '校验通过' : '草稿' }}</span></div>

        <section v-if="step === 1" class="form-grid">
          <label>实验名称<input v-model="version.spec.name" class="input" :disabled="!editable" /></label>
          <label>实验编号<input :value="lab?.code" class="input" disabled /></label>
          <YkSelect v-model="category" label="实验分类" :options="categories" :disabled="!editable" />
          <label>建议时长<input v-model.number="version.spec.duration_minutes" type="number" class="input" :disabled="!editable" /></label>
          <label>总分<input v-model.number="version.spec.total_score" type="number" class="input" :disabled="!editable" /></label>
          <label class="wide">实验目标<textarea class="input" rows="3" :value="lab?.objective" disabled /></label>
          <div class="wide template-choice"><b>已应用模板：双机密码学实验</b><p class="muted">Student + Target 两台 Ubuntu，适合 RSA、AES 和哈希实验。</p></div>
          <button v-if="version.status === 'PUBLISHED'" class="yk-button primary wide" :disabled="busy" @click="createDraft">从已发布版本创建可编辑草稿</button>
          <button v-else class="yk-button primary wide" :disabled="busy" @click="act(async () => { version = await saveVersion(version!); message = '基本信息已保存到数据库。' })">保存草稿</button>
        </section>

        <section v-else-if="step === 2">
          <div class="topology-summary"><span class="badge success">{{ version.spec.nodes.length }} 个节点</span><span class="badge">{{ version.spec.networks[0]?.network_key }}</span><span class="badge success">学生隔离</span></div>
          <div class="topology-canvas">
            <div v-for="(node, index) in version.spec.nodes" :key="node.node_key" class="topology-node" :draggable="editable" :style="{ left: `${node.position_x}px`, top: `${node.position_y}px` }" @dragend="saveTopology($event, index)"><b>{{ node.node_key }}</b><small>{{ node.display_name }}</small><small>{{ node.cpu_limit }} 核 / {{ node.memory_mb }} MB</small></div>
          </div>
          <div class="card inset"><b>网络环境</b><p>{{ version.spec.networks[0]?.cidr_policy }} · {{ version.spec.networks[0]?.internet_access ? '允许互联网访问' : '禁止互联网访问' }} · 学生间隔离</p></div>
        </section>

        <section v-else-if="step === 3" class="table-scroll"><table class="data-table"><thead><tr><th>节点</th><th>基础设施镜像引用</th><th>固定摘要</th><th>安全约束</th></tr></thead><tbody><tr v-for="binding in version.spec.image_bindings" :key="binding.node_key"><td>{{ binding.node_key }}</td><td>{{ binding.infra_image_id }}</td><td class="digest">{{ binding.digest }}</td><td><span class="badge success">非特权 · 隔离网络</span></td></tr></tbody></table><p class="muted">这里只保存 D 线镜像标识与摘要引用，不拉取镜像、不启动容器。</p></section>

        <section v-else-if="step === 4" class="dag-layout">
          <div class="dag-list"><template v-for="(dagStep, index) in version.spec.steps" :key="dagStep.node_key"><div class="dag-node"><b>{{ index + 1 }}. {{ dagStep.name }}</b><small>{{ dagStep.description }}</small></div><div v-if="index < version.spec.steps.length - 1" class="dag-arrow">↓</div></template></div>
          <div><div class="score-card"><span>得分完整性 · {{ version.spec.checkpoints.length }} 个得分点</span><b :class="{ bad: score !== version.spec.total_score }">{{ score }} / {{ version.spec.total_score }}</b></div><table class="data-table compact"><thead><tr><th>得分点</th><th>判定类型</th><th>分值</th></tr></thead><tbody><tr v-for="checkpoint in version.spec.checkpoints" :key="checkpoint.checkpoint_id"><td>{{ checkpoint.name }}</td><td>{{ checkpoint.judge_type }}</td><td>{{ checkpoint.score }}</td></tr></tbody></table></div>
        </section>

        <section v-else-if="step === 5" class="release-panel"><h3>发布对象</h3><YkCheck v-model="selectedClass" label="网络安全 2301 班 · 43 人" /><dl><dt>课程引用</dt><dd>course_data_security</dd><dt>班级引用</dt><dd>class_netsec_2301</dd><dt>每人尝试</dt><dd>{{ version.spec.runtime_policy.max_attempts }} 次</dd><dt>超时</dt><dd>{{ version.spec.runtime_policy.timeout_minutes }} 分钟</dd></dl><button class="yk-button primary" :disabled="busy || version.status !== 'PUBLISHED' || !selectedClass" @click="prepareRelease">创建发布配置并预检</button><p v-if="version.status !== 'PUBLISHED'" class="muted">请先在第 6 步将校验通过的实验版本发布并冻结。</p></section>

        <section v-else class="preflight-grid"><div class="card inset"><h3>发布门禁</h3><p>✓ 基本信息完整</p><p>✓ 2 个节点、隔离网络</p><p>✓ 镜像摘要固定</p><p>✓ DAG 无环</p><p>✓ 得分合计 {{ score }}/{{ version.spec.total_score }}</p><button v-if="version.status === 'DRAFT'" class="yk-button primary" :disabled="busy" @click="runValidation">执行静态预检</button><button v-else-if="version.status === 'READY'" class="yk-button primary" :disabled="busy" @click="freezeVersion">发布并冻结 V{{ version.version }}</button><span v-else class="badge success">版本已冻结，不可覆盖</span></div><div class="card inset"><h3>教师预演</h3><p>D 线运行底座负责容器、网络与受限判定器。C 线只提交预演请求。</p><button class="yk-button primary" :disabled="busy || !release" @click="preview">请求教师预演</button><p v-if="!release" class="muted">请先在第 5 步创建发布配置并通过预检。</p></div></section>

        <footer class="builder-footer"><button class="yk-button" :disabled="step === 1" @click="step--">上一步</button><span>步骤 {{ step }} / 6</span><button class="yk-button primary" :disabled="step === 6" @click="step++">下一步</button></footer>
      </main>
    </div>
  </template>
</template>
