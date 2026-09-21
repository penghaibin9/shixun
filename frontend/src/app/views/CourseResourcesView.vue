<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import YkModal from '../../components/common/YkModal.vue'
import YkPageHeader from '../../components/common/YkPageHeader.vue'
import YkSelect from '../../components/common/YkSelect.vue'
import { resourceApi, type ApiError, type Audit, type LessonResource, type Resource, type ResourceReadiness } from '../api'

const route = useRoute()
const page = computed(() => String(route.meta.page || 'overview'))
const loading = ref(true), error = ref(''), lessons = ref<LessonResource[]>([]), resources = ref<Resource[]>([]), audit = ref<Audit | null>(null)
const readiness = ref<ResourceReadiness | null>(null)
const coverage = ref<{ lesson_id: string; lesson_code: string; types: string[]; passed: boolean }[]>([])
const manifest = ref<{ status: string; version_no: number | null; theory_lessons: number; lab_lessons: number; audit: Audit; content_declaration: string } | null>(null)
const statusFilter = ref(''), typeFilter = ref(''), nameFilter = ref('')
const uploadOpen = ref(false), uploadName = ref(''), uploadType = ref('PPT'), uploadLesson = ref(''), uploadFile = ref<File | null>(null), uploading = ref(false), uploadError = ref(''), uploadMessage = ref('')
const titles: Record<string, [string, string]> = {
  overview: ['教学资源生产与课程建设中心', '每个课时应有什么、缺什么、由谁审核、能否交付均来自真实资源事实。'],
  blueprint: ['课程蓝图', '37 个理论课时按采购知识点结构展开，第 7 章固定为 4 节。'],
  theory: ['理论课时资源', '每课时以 PPT（演示文稿）、真实讲解视频和四类练习作为最小完整单元。'],
  labs: ['实验课程资源', '8 类核心实验映射为 12 个教学课时；B 线维护资源，实验定义由 C 线提供。'],
  ppt: ['PPT / 课时讲义', '发布前必须完成人工内容、溢出、动画遮挡和版权抽检。'],
  video: ['视频中心', '只显示媒体解析写入的真实时长；未上传视频不会显示原型示例时长。'],
  questions: ['题库中心', '每课时默认 4 题，并覆盖填空、单选、多选、判断。'],
  procurement: ['采购条款映射', '跨域条款仅展示契约归属，不直接读取其他业务线数据表。'],
  audit: ['资源完整性审计', '按当前数据库中的真实资源动态计算，阻断项不会被写死。'],
  delivery: ['发布与最终交付', '存在一个阻断项也不能冻结交付版本。'],
}
const filtered = computed(() => resources.value.filter(item => (!statusFilter.value || item.status === statusFilter.value) && (!typeFilter.value || item.resource_type === typeFilter.value) && (!nameFilter.value || item.name.includes(nameFilter.value))))
const theory = computed(() => lessons.value.filter(item => item.lesson_kind === 'THEORY'))
const labs = computed(() => lessons.value.filter(item => item.lesson_kind === 'LAB'))
const uploadLessons = computed(() => (uploadType.value === 'LAB_FILE' ? labs.value : uploadType.value === 'PPT' ? theory.value : lessons.value).map(item => ({ value: item.lesson_id, label: `${item.lesson_code} · ${item.title}` })))
const chapterCounts = computed(() => theory.value.reduce<Record<number, number>>((all, item) => ({ ...all, [item.chapter_no || 0]: (all[item.chapter_no || 0] || 0) + 1 }), {}))
const statusText = (status: string) => ({ DRAFT: '草稿', PENDING_REVIEW: '待审核', PUBLISHED: '已发布', FROZEN: '已冻结', REJECTED: '已驳回' }[status] || '未知状态')
const typeText = (type: string) => ({ PPT: 'PPT（演示文稿）', VIDEO: '视频', QUESTION_BANK: '题库', LAB_FILE: '实验文件包' }[type] || '其他资源')

async function load() {
  loading.value = true; error.value = ''
  try {
    const [blueprint, allResources, currentReadiness] = await Promise.all([resourceApi.blueprint(), resourceApi.resources(), resourceApi.readiness()])
    lessons.value = blueprint.items; resources.value = allResources.items; readiness.value = currentReadiness
    if (page.value === 'questions') coverage.value = (await resourceApi.coverage()).items
    if (page.value === 'audit' || page.value === 'procurement') audit.value = await resourceApi.latestAudit()
    if (page.value === 'delivery') manifest.value = await resourceApi.manifest()
  } catch (reason) { error.value = (reason as ApiError).message || '课程资源服务暂时不可用' }
  finally { loading.value = false }
}
async function runAudit() { loading.value = true; try { audit.value = await resourceApi.audit() } catch (reason) { error.value = (reason as ApiError).message } finally { loading.value = false } }
async function freezeDelivery() { if (!confirm('确认冻结当前课程资源交付版本？冻结后历史版本不可覆盖。')) return; try { await resourceApi.freeze(); manifest.value = await resourceApi.manifest() } catch (reason) { error.value = (reason as ApiError).message } }
function openUpload() { uploadName.value = ''; uploadType.value = 'PPT'; uploadLesson.value = theory.value[0]?.lesson_id || ''; uploadFile.value = null; uploadError.value = ''; uploadOpen.value = true }
watch(uploadType, () => { if (!uploadLessons.value.some(item => item.value === uploadLesson.value)) uploadLesson.value = uploadLessons.value[0]?.value || '' })
async function submitUpload() {
  if (!uploadName.value.trim() || !uploadLesson.value || !uploadFile.value) { uploadError.value = '请填写资源名称、选择课时并选择文件。'; return }
  uploading.value = true; uploadError.value = ''
  try {
    const file = await resourceApi.uploadFile(uploadFile.value)
    const resource = await resourceApi.createResource({ lesson_id: uploadLesson.value, name: uploadName.value.trim(), resource_type: uploadType.value })
    await resourceApi.createVersion(resource.resource_id, { file_id: file.file_id, sha256: file.sha256 })
    uploadOpen.value = false; uploadMessage.value = '真实文件已上传并登记为草稿版本，请继续完成质量检查和独立审核。'
    await load()
  } catch (reason) { uploadError.value = (reason as ApiError).message || '上传失败，请检查文件后重试。' }
  finally { uploading.value = false }
}
async function downloadResource(item: Resource) {
  try {
    const blob = await resourceApi.download(item.resource_id), url = URL.createObjectURL(blob), link = document.createElement('a')
    link.href = url; link.download = item.name; link.click(); URL.revokeObjectURL(url)
  } catch (reason) { error.value = (reason as ApiError).message || '文件下载失败。' }
}
onMounted(load); watch(page, load)
</script>

<template>
  <div class="resource-page">
    <YkPageHeader :title="titles[page][0]" :description="titles[page][1]"><template #actions><button v-if="page === 'audit'" class="yk-button primary" @click="runAudit">重新执行全量审计</button><button v-if="page === 'delivery'" class="yk-button primary" @click="freezeDelivery">冻结交付版本</button></template></YkPageHeader>
    <div v-if="loading" class="state-panel">正在读取课程资源事实…</div>
    <div v-else-if="error" class="state-panel error-state"><b>暂时无法加载</b><span>{{ error }}</span><button class="yk-button" @click="load">重试</button></div>
    <template v-else>
      <template v-if="page === 'overview'">
        <div class="card filter-bar"><YkSelect v-model="statusFilter" aria-label="发布状态" :options="[{label:'全部发布状态',value:''},{label:'草稿',value:'DRAFT'},{label:'待审核',value:'PENDING_REVIEW'},{label:'已发布',value:'PUBLISHED'},{label:'已冻结',value:'FROZEN'}]"/><input v-model="nameFilter" class="yk-input" placeholder="按资源名称搜索"/><YkSelect v-model="typeFilter" aria-label="资源类型" :options="[{label:'全部类型',value:''},{label:'PPT（演示文稿）',value:'PPT'},{label:'视频',value:'VIDEO'},{label:'题库',value:'QUESTION_BANK'},{label:'实验文件',value:'LAB_FILE'}]"/><button class="yk-button primary" @click="openUpload">＋ 新增资源</button></div>
        <p v-if="uploadMessage" class="success-notice">{{ uploadMessage }}</p>
        <div class="grid grid-4 summary-grid"><div class="card kpi"><span>理论课时</span><b>{{ theory.length }} / 37</b></div><div class="card kpi"><span>实验课时</span><b>{{ labs.length }} / 12</b></div><div class="card kpi"><span>真实资源记录</span><b>{{ resources.length }}</b></div><div class="card kpi"><span>交付阻断项</span><b>{{ readiness?.blocking ?? '—' }}</b></div></div>
        <div class="card table-card"><table class="data-table"><thead><tr><th>资源名称</th><th>课时</th><th>类型</th><th>发布状态</th><th>文件</th></tr></thead><tbody><tr v-for="item in filtered" :key="item.resource_id"><td>{{ item.name }}</td><td>{{ item.lesson_id || '课程级' }}</td><td>{{ typeText(item.resource_type) }}</td><td><span class="badge">{{ statusText(item.status) }}</span></td><td><button v-if="item.latest_version" class="yk-button" @click="downloadResource(item)">下载</button><span v-else class="muted">尚无版本</span></td></tr><tr v-if="!filtered.length"><td colspan="5" class="empty-cell">尚无满足条件的真实资源，请上传后进入版本审核流程。</td></tr></tbody></table></div>
      </template>
      <template v-else-if="page === 'blueprint'">
        <div class="chapter-grid"><div v-for="chapter in 7" :key="chapter" class="card chapter-card"><span class="badge">第 {{ chapter }} 章</span><b>{{ chapterCounts[chapter] || 0 }}</b><span>理论课时</span></div></div>
        <div class="card table-card"><table class="data-table"><thead><tr><th>课时</th><th>章节</th><th>知识点</th><th>资源状态</th></tr></thead><tbody><tr v-for="item in theory" :key="item.lesson_id"><td>{{ item.lesson_code }}</td><td>第 {{ item.chapter_no }} 章</td><td>{{ item.title }}</td><td><span class="badge">待上传真实内容</span></td></tr></tbody></table></div>
      </template>
      <template v-else-if="page === 'theory'">
        <div class="lesson-grid"><article v-for="item in theory" :key="item.lesson_id" class="card lesson-card"><div><span class="badge">第 {{ item.chapter_no }} 章</span><span class="badge warn">真实内容待上传</span></div><h3>{{ item.lesson_code }} {{ item.title }}</h3><p>PPT（演示文稿） · 真实讲解视频 · 四类题型 · 独立审核</p></article></div>
      </template>
      <template v-else-if="page === 'labs'">
        <div class="card core-map"><b>8 类核心实验映射</b><span v-for="core in [...new Set(labs.map(x => x.core_experiment))]" :key="core || ''" class="badge">{{ core }}</span></div>
        <div class="card table-card"><table class="data-table"><thead><tr><th>课时</th><th>核心实验</th><th>主题</th><th>结构化介绍</th><th>真实内容</th></tr></thead><tbody><tr v-for="item in labs" :key="item.lesson_id"><td>{{ item.lesson_code }}</td><td>{{ item.core_experiment }}</td><td>{{ item.title }}</td><td><details><summary>查看介绍</summary><p><b>目的：</b>{{ item.purpose }}</p><p><b>环境：</b>{{ item.environment }}</p><p><b>原理：</b>{{ item.principle }}</p></details></td><td><span class="badge warn">文件/视频/题库待上传</span></td></tr></tbody></table></div>
      </template>
      <template v-else-if="page === 'ppt' || page === 'video'">
        <div class="grid grid-4 summary-grid"><div class="card kpi"><span>要求课时</span><b>{{ page === 'ppt' ? 37 : 49 }}</b></div><div class="card kpi"><span>已登记真实文件</span><b>{{ resources.filter(r => r.resource_type === (page === 'ppt' ? 'PPT' : 'VIDEO') && r.latest_version).length }}</b></div><div class="card kpi"><span>门禁通过</span><b>{{ page === 'ppt' ? readiness?.ppt.ready : (readiness?.theory_video.ready || 0) + (readiness?.lab_video.ready || 0) }}</b></div><div class="card kpi"><span>{{ page === 'ppt' ? '人工抽检' : '真实时长' }}</span><b>按证据核验</b></div></div><div class="state-panel">只有已上传、已解析、已独立审核并发布的真实教学{{ page === 'ppt' ? '演示文稿' : '视频' }}才计入门禁。</div>
      </template>
      <template v-else-if="page === 'questions'">
        <div class="grid grid-4 summary-grid"><div class="card kpi"><span>课时总数</span><b>{{ coverage.length }}</b></div><div class="card kpi"><span>覆盖通过</span><b>{{ readiness?.question_lessons.ready || 0 }} / 49</b></div><div class="card kpi"><span>已审核发布题目</span><b>{{ readiness?.published_questions.ready || 0 }} / 196</b></div><div class="card kpi"><span>四种题型</span><b>填/单/多/判</b></div></div><div class="card table-card"><table class="data-table"><thead><tr><th>课时</th><th>已有题型</th><th>门禁</th></tr></thead><tbody><tr v-for="item in coverage" :key="item.lesson_id"><td>{{ item.lesson_code }}</td><td>{{ item.types.join('、') || '尚无已审核题目' }}</td><td><span class="badge" :class="{ warn: !item.passed }">{{ item.passed ? '通过' : '阻断' }}</span></td></tr></tbody></table></div>
      </template>
      <template v-else-if="page === 'procurement'">
        <div class="card table-card"><table class="data-table"><thead><tr><th>采购要求</th><th>事实所有者</th><th>验收证据</th></tr></thead><tbody><tr v-for="item in audit?.procurement_mapping" :key="item.requirement"><td>{{ item.requirement }}</td><td>{{ item.owner }}</td><td>{{ item.evidence }}</td></tr></tbody></table></div>
      </template>
      <template v-else-if="page === 'audit' && audit">
        <div class="grid grid-4 summary-grid"><div class="card kpi"><span>检查点</span><b>{{ audit.total }}</b></div><div class="card kpi"><span>通过</span><b>{{ audit.pass }}</b></div><div class="card kpi"><span>提醒</span><b>{{ audit.warning }}</b></div><div class="card kpi danger-kpi"><span>阻断</span><b>{{ audit.blocking }}</b></div></div><div class="card blockers"><h3>真实阻断项</h3><ul><li v-for="item in audit.blocking_items.slice(0, 30)" :key="item">{{ item }}</li></ul><p v-if="audit.blocking_items.length > 30" class="muted">其余 {{ audit.blocking_items.length - 30 }} 项已保留在审计 JSON（数据文本）中。</p></div>
      </template>
      <template v-else-if="page === 'delivery' && manifest">
        <div class="grid grid-2"><div class="card delivery-card"><span class="badge" :class="{ warn: manifest.status === 'BLOCKED' }">{{ manifest.status === 'BLOCKED' ? '存在阻断' : '可交付' }}</span><h2>课程资源交付清单</h2><p>{{ manifest.content_declaration }}</p><dl><dt>理论课时</dt><dd>{{ manifest.theory_lessons }}</dd><dt>实验课时</dt><dd>{{ manifest.lab_lessons }}</dd><dt>阻断项</dt><dd>{{ manifest.audit.blocking }}</dd></dl></div><div class="card"><h3>交付文件</h3><p>JSON（结构化清单）与 XLSX（电子表格）均由当前数据库实时生成。</p><a class="yk-button" href="/api/v1/resources/delivery/manifest.xlsx">导出 XLSX（电子表格）</a></div></div>
      </template>
    </template>
    <YkModal :open="uploadOpen" title="上传真实课程资源" @close="uploadOpen = false">
      <form class="form-grid" @submit.prevent="submitUpload">
        <label><span>资源名称</span><input v-model="uploadName" class="input" maxlength="255" placeholder="例如：第 1.1 课时演示文稿" /></label>
        <YkSelect v-model="uploadType" label="资源类型" :options="[{label:'PPT（演示文稿）',value:'PPT'},{label:'讲解视频',value:'VIDEO'},{label:'实验文件包',value:'LAB_FILE'}]" />
        <div class="wide"><YkSelect v-model="uploadLesson" label="关联课时" :options="uploadLessons" /></div>
        <label class="wide"><span>选择真实文件</span><input class="input" type="file" :accept="uploadType === 'PPT' ? '.ppt,.pptx' : uploadType === 'VIDEO' ? '.mp4,.webm,.mov' : '.zip,.tar,.gz'" @change="uploadFile = ($event.target as HTMLInputElement).files?.[0] || null" /></label>
        <p v-if="uploadError" class="wide status-error">{{ uploadError }}</p>
        <div class="wide actions"><button class="yk-button primary" type="submit" :disabled="uploading">{{ uploading ? '正在上传并校验…' : '上传并建立草稿版本' }}</button><button class="yk-button" type="button" @click="uploadOpen = false">取消</button></div>
      </form>
    </YkModal>
  </div>
</template>
