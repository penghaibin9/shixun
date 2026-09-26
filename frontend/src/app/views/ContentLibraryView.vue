<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { contentPackApi, type ContentPackSummary, type ContentSource, type ExternalRuntimeContract, type WebLabCandidate } from '../api'

const packs = ref<ContentPackSummary[]>([])
const sources = ref<ContentSource[]>([])
const externalContracts = ref<ExternalRuntimeContract[]>([])
const externalRule = ref('')
const labs = ref<WebLabCandidate[]>([])
const seedDomains = ref<{ source_category: string; yueke_course: string; status: string }[]>([])
const vulhubFile = ref<File>()
const composeFile = ref<File>()
const atomicFile = ref<File>()
const dojoFile = ref<File>()
const previewCount = ref<number | null>(null)
const atomicPreview = ref<{ attack_technique: string; display_name: string; test_count: number }>()
const dojoPreview = ref<{ dojo_id: string; name: string; module_count: number }>()
const composeResult = ref<{ passed: boolean; findings: { code: string; message: string; service?: string; blocking: boolean }[] }>()
const message = ref('')

async function load() {
  try {
    const [packResult, sourceResult, contractResult, labResult, seedResult] = await Promise.all([
      contentPackApi.list(),
      contentPackApi.sources(),
      contentPackApi.externalRuntimeContracts(),
      contentPackApi.webLabCandidates(),
      contentPackApi.seedDomainMap(),
    ])
    packs.value = packResult.items
    sources.value = sourceResult.items
    externalContracts.value = contractResult.items
    externalRule.value = contractResult.rule
    labs.value = labResult.labs
    seedDomains.value = seedResult.domain_map
  } catch (error) {
    message.value = (error as { message?: string }).message || '内容包加载失败'
  }
}

async function previewVulhub() {
  if (!vulhubFile.value) return
  const result = await contentPackApi.previewVulhub(vulhubFile.value)
  previewCount.value = result.total
  message.value = `Vulhub 索引已解析：${result.total} 个候选环境；未自动运行任何容器。`
}

async function previewAtomic() {
  if (!atomicFile.value) return
  atomicPreview.value = await contentPackApi.previewAtomic(atomicFile.value)
  message.value = `Atomic Red Team 仅解析元数据：${atomicPreview.value.attack_technique} · ${atomicPreview.value.test_count} 个测试；未导入执行命令。`
}

async function previewDojo() {
  if (!dojoFile.value) return
  dojoPreview.value = await contentPackApi.previewDojo(dojoFile.value)
  message.value = `pwn.college dojo 仅解析课程结构：${dojoPreview.value.name} · ${dojoPreview.value.module_count} 个模块；未复制挑战内容。`
}

async function scanCompose() {
  if (!composeFile.value) return
  composeResult.value = await contentPackApi.scanCompose(composeFile.value)
  message.value = composeResult.value.passed ? 'Compose 静态安全门禁通过，可继续人工/镜像审核。' : 'Compose 被安全门禁阻断，请先处理风险项。'
}

onMounted(load)
</script>

<template>
  <div>
    <div class="hero">
      <div><h1>内容包中心</h1><p>统一管理原创课程、外部靶场候选、许可证和导入安全门禁。</p></div>
      <span class="badge">商业交付安全优先</span>
    </div>
    <p v-if="message" class="status-ok" aria-live="polite">{{ message }}</p>

    <section class="card">
      <div class="section-head"><div><h3>正式课程包</h3><p class="muted">课程内容与第三方运行依赖分离，外部项目不会直接覆盖你的课程事实。</p></div></div>
      <div class="grid grid-2">
        <article v-for="pack in packs" :key="pack.pack_id" class="card">
          <span class="badge">{{ pack.content_origin }}</span>
          <h3>{{ pack.title }}</h3>
          <p>{{ pack.theory_lessons }} 个理论课时 · {{ pack.lab_lessons }} 个实验课时 · {{ pack.language }}</p>
          <p class="muted">版本 {{ pack.version }} · 商业内容包：{{ pack.commercial_bundle_allowed ? '允许' : '禁止' }}</p>
        </article>
      </div>
    </section>

    <section class="card section-gap">
      <div class="section-head"><div><h3>外部来源许可证</h3><p class="muted">ALLOW 不等于自动发布；仍需保留许可证声明和运行安全证据。</p></div></div>
      <table class="data-table">
        <thead><tr><th>来源</th><th>许可证</th><th>用途</th><th>判定</th><th>原因</th></tr></thead>
        <tbody><tr v-for="source in sources" :key="source.name"><td>{{ source.name }}</td><td>{{ source.license_id }}</td><td>{{ source.use_mode }}</td><td><span class="badge">{{ source.license_decision }}</span></td><td>{{ source.license_reason }}</td></tr></tbody>
      </table>
    </section>

    <section class="card section-gap">
      <div class="section-head">
        <div>
          <h3>外部靶场接入门禁</h3>
          <p class="muted">{{ externalRule }}</p>
        </div>
      </div>
      <table class="data-table">
        <thead><tr><th>来源</th><th>接入方式</th><th>许可证</th><th>当前状态</th><th>直接运行源码 Compose</th><th>融合外部前端</th><th>还必须通过</th></tr></thead>
        <tbody>
          <tr v-for="item in externalContracts" :key="item.source_name">
            <td><b>{{ item.source_name }}</b></td>
            <td>{{ item.integration_mode === 'ISOLATED_TARGET_SERVICE' ? '独立隔离靶场' : '元数据转实验定义' }}</td>
            <td>{{ item.license_id }} · {{ item.license_decision }}</td>
            <td><span class="badge">{{ item.current_status }}</span></td>
            <td>{{ item.source_compose_execution_allowed ? '允许' : '禁止' }}</td>
            <td>{{ item.external_frontend_embedding_allowed ? '允许' : '禁止' }}</td>
            <td>{{ item.required_gates.join(' → ') }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="card section-gap">
      <div class="section-head"><div><h3>Web 安全 12 实验就绪度</h3><p class="muted">没有固定镜像摘要和真实 Linux 证据的实验明确显示等待，不伪造已发布状态。</p></div></div>
      <table class="data-table">
        <thead><tr><th>课时</th><th>实验</th><th>来源</th><th>许可证</th><th>运行状态</th><th>说明</th></tr></thead>
        <tbody><tr v-for="lab in labs" :key="lab.lab_definition_id"><td>{{ lab.lesson_code }}</td><td>{{ lab.title }}</td><td>{{ lab.source }}</td><td>{{ lab.license }}</td><td><span class="badge">{{ lab.runtime_status }}</span></td><td>{{ lab.reason }}</td></tr></tbody>
      </table>
    </section>

    <section class="card section-gap">
      <div class="section-head"><div><h3>SEED Labs 知识域映射</h3><p class="muted">只参考公开知识域，中文讲义/题库/实验由跃科原创，不直接翻译其非商业教材。</p></div></div>
      <table class="data-table"><thead><tr><th>SEED 公开分类</th><th>跃科原创中文课程</th><th>状态</th></tr></thead><tbody><tr v-for="item in seedDomains" :key="item.source_category"><td>{{ item.source_category }}</td><td>{{ item.yueke_course }}</td><td><span class="badge">{{ item.status }}</span></td></tr></tbody></table>
    </section>

    <section class="grid grid-2 section-gap">
      <article class="card">
        <h3>Vulhub 索引预检</h3><p class="muted">上传 environments.toml，只解析元数据，不启动 Docker。</p>
        <input type="file" accept=".toml,text/plain" @change="vulhubFile=($event.target as HTMLInputElement).files?.[0]">
        <button class="yk-button primary" :disabled="!vulhubFile" @click="previewVulhub">解析候选环境</button>
        <p v-if="previewCount !== null">候选数量：{{ previewCount }}</p>
      </article>
      <article class="card">
        <h3>Compose 安全扫描</h3><p class="muted">拦截 privileged、host network、Docker Socket、危险宿主挂载等。</p>
        <input type="file" accept=".yml,.yaml,text/yaml" @change="composeFile=($event.target as HTMLInputElement).files?.[0]">
        <button class="yk-button primary" :disabled="!composeFile" @click="scanCompose">执行静态门禁</button>
        <ul v-if="composeResult?.findings.length"><li v-for="item in composeResult.findings" :key="item.code">{{ item.code }}：{{ item.message }}</li></ul>
      </article>
    </section>

    <section class="grid grid-2 section-gap">
      <article class="card">
        <h3>Atomic Red Team 元数据预检</h3>
        <p class="muted">只读取 ATT&CK 编号、测试名称、平台和执行器类型，不导入或执行命令。</p>
        <input type="file" accept=".yml,.yaml,text/yaml" @change="atomicFile=($event.target as HTMLInputElement).files?.[0]">
        <button class="yk-button" :disabled="!atomicFile" @click="previewAtomic">解析 Atomic 元数据</button>
        <p v-if="atomicPreview">{{ atomicPreview.attack_technique }} · {{ atomicPreview.display_name }} · {{ atomicPreview.test_count }} 项</p>
      </article>
      <article class="card">
        <h3>pwn.college Dojo 结构预检</h3>
        <p class="muted">只读取 dojo/module 结构，用于课程编排参考，不复制外部挑战正文。</p>
        <input type="file" accept=".yml,.yaml,text/yaml" @change="dojoFile=($event.target as HTMLInputElement).files?.[0]">
        <button class="yk-button" :disabled="!dojoFile" @click="previewDojo">解析 Dojo 结构</button>
        <p v-if="dojoPreview">{{ dojoPreview.name }} · {{ dojoPreview.module_count }} 个模块</p>
      </article>
    </section>
  </div>
</template>

<style scoped>
.section-gap { margin-top: 14px; }
input[type="file"] { display: block; margin: 12px 0; }
</style>
