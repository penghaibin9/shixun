<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import YkDrawer from '../../components/common/YkDrawer.vue'
import YkModal from '../../components/common/YkModal.vue'
import YkPageHeader from '../../components/common/YkPageHeader.vue'
import YkRadio from '../../components/common/YkRadio.vue'
import YkSelect from '../../components/common/YkSelect.vue'
import YkTabs from '../../components/common/YkTabs.vue'
import { resourceApi, resourceUserId, type ApiError, type Audit, type LessonResource, type QuestionImportJob, type QuestionReviewItem, type Resource, type ResourceReadiness } from '../api'

const route = useRoute()
const page = computed(() => String(route.meta.page || 'overview'))
const loading = ref(true), error = ref(''), lessons = ref<LessonResource[]>([]), resources = ref<Resource[]>([]), audit = ref<Audit | null>(null)
const readiness = ref<ResourceReadiness | null>(null)
const coverage = ref<{ lesson_id: string; lesson_code: string; types: string[]; passed: boolean }[]>([])
const manifest = ref<{ status: string; version_no: number | null; theory_lessons: number; lab_lessons: number; audit: Audit; content_declaration: string } | null>(null)
const statusFilter = ref(''), typeFilter = ref(''), nameFilter = ref('')
const uploadOpen = ref(false), uploadName = ref(''), uploadType = ref('PPT'), uploadLesson = ref(''), uploadFile = ref<File | null>(null), uploading = ref(false), uploadError = ref(''), uploadMessage = ref('')
const questionTab = ref('overview'), questionImportOpen = ref(false), questionFile = ref<File | null>(null), questionImporting = ref(false), questionImportError = ref(''), questionImportMessage = ref('')
const questionImportJob = ref<QuestionImportJob | null>(null), questionReviewItems = ref<QuestionReviewItem[]>([]), questionReviewTotal = ref(0), questionReviewLoading = ref(false)
const selectedQuestion = ref<QuestionReviewItem | null>(null), reviewDecision = ref<'APPROVED' | 'REJECTED'>('APPROVED'), reviewComment = ref(''), reviewSubmitting = ref(false), reviewError = ref(''), reviewMessage = ref('')
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
const questionTypeText = (type: string) => ({ FILL: '填空题', SINGLE: '单选题', MULTIPLE: '多选题', TRUE_FALSE: '判断题' }[type] || '未知题型')
const importStatusText = (status: string) => ({ PENDING: '等待处理', PROCESSING: '正在处理', COMPLETED: '处理完成', SUCCEEDED: '处理完成', VALIDATION_FAILED: '校验未通过', PARTIAL: '部分成功', FAILED: '处理失败', CANCELLED: '已取消' }[status] || '状态待确认')
function errorFieldText(field: string) {
  const translated = ({ lesson_id: '课时标识', lesson_code: '课时编号', question_type: '题型', stem: '题干', options: '选项', answer: '答案', explanation: '解析' } as Record<string, string>)[field]
  const templateLabel = field.replace(/\*/g, '').trim()
  return translated || (/[一-鿿]/.test(templateLabel) ? templateLabel : '当前行')
}
const errorRowText = (rowNumber: number | null) => rowNumber && rowNumber > 0 ? `第 ${rowNumber} 行` : '文件级'
const questionTabs = computed(() => [{ label: '题库总览', value: 'overview' }, { label: '批量导入', value: 'import' }, { label: `待审核（${questionReviewTotal.value}）`, value: 'review' }])
const isOwnQuestion = (item: QuestionReviewItem) => typeof item.can_review === 'boolean' ? !item.can_review : (!!resourceUserId && item.created_by === resourceUserId)
const questionCreatorText = (item: QuestionReviewItem) => isOwnQuestion(item) ? '本人提交' : '其他教师'

async function load() {
  loading.value = true; error.value = ''
  try {
    const [blueprint, allResources, currentReadiness] = await Promise.all([resourceApi.blueprint(), resourceApi.resources(), resourceApi.readiness()])
    lessons.value = blueprint.items; resources.value = allResources.items; readiness.value = currentReadiness
    if (page.value === 'questions') {
      const [coverageResult, reviewQueue] = await Promise.all([resourceApi.coverage(), resourceApi.questionReviewQueue()])
      coverage.value = coverageResult.items; questionReviewItems.value = reviewQueue.items; questionReviewTotal.value = reviewQueue.total
    }
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
function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob), link = document.createElement('a')
  link.href = url; link.download = filename; link.click(); URL.revokeObjectURL(url)
}
async function downloadQuestionTemplate() {
  questionImportError.value = ''
  try { saveBlob(await resourceApi.questionImportTemplate(), 'question-import-template.xlsx') }
  catch (reason) { questionImportError.value = (reason as ApiError).message || '题库模板下载失败，请稍后重试。' }
}
function openQuestionImport() {
  questionFile.value = null; questionImportError.value = ''; questionImportOpen.value = true
}
function selectQuestionFile(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0] || null
  if (file && !file.name.toLowerCase().endsWith('.xlsx')) {
    questionFile.value = null; questionImportError.value = '仅支持 XLSX（电子表格）文件，请重新选择。'; input.value = ''; return
  }
  questionFile.value = file; questionImportError.value = ''
}
async function refreshQuestionImportJob() {
  if (!questionImportJob.value?.job_id) return
  try { questionImportJob.value = await resourceApi.questionImportJob(questionImportJob.value.job_id) }
  catch (reason) { questionImportError.value = (reason as ApiError).message || '导入结果暂时无法刷新。' }
}
async function loadQuestionReviewQueue() {
  questionReviewLoading.value = true
  try {
    const result = await resourceApi.questionReviewQueue(); questionReviewItems.value = result.items; questionReviewTotal.value = result.total
  } catch (reason) { reviewError.value = (reason as ApiError).message || '待审核队列暂时无法加载。' }
  finally { questionReviewLoading.value = false }
}
async function submitQuestionImport() {
  if (!questionFile.value) { questionImportError.value = '请先选择 XLSX（电子表格）题库文件。'; return }
  questionImporting.value = true; questionImportError.value = ''; questionImportMessage.value = ''
  try {
    questionImportJob.value = await resourceApi.importQuestions(questionFile.value)
    questionImportOpen.value = false; questionTab.value = 'import'
    await refreshQuestionImportJob(); await loadQuestionReviewQueue()
    questionImportMessage.value = questionImportJob.value?.status === 'COMPLETED'
      ? `已导入 ${questionImportJob.value.imported_count} 道题目，全部进入独立审核队列。`
      : questionImportJob.value?.status === 'VALIDATION_FAILED'
        ? '文件校验未通过，尚未写入题库。请修正全部错误行后重新导入。'
        : '导入任务已受理，请刷新处理结果。'
  } catch (reason) { questionImportError.value = (reason as ApiError).message || '题库导入失败，请检查文件后重试。' }
  finally { questionImporting.value = false }
}
async function downloadQuestionErrors() {
  if (!questionImportJob.value?.job_id) return
  try { saveBlob(await resourceApi.questionImportErrors(questionImportJob.value.job_id), `question-import-errors-${questionImportJob.value.job_id}.xlsx`) }
  catch (reason) { questionImportError.value = (reason as ApiError).message || '错误明细下载失败，请稍后重试。' }
}
function openQuestionReview(item: QuestionReviewItem) {
  if (isOwnQuestion(item)) return
  selectedQuestion.value = item; reviewDecision.value = 'APPROVED'; reviewComment.value = ''; reviewError.value = ''
}
async function submitQuestionReview() {
  if (!selectedQuestion.value || isOwnQuestion(selectedQuestion.value)) { reviewError.value = '出题人不能审核自己的题目，需由其他审核人处理。'; return }
  if (reviewDecision.value === 'REJECTED' && !reviewComment.value.trim()) { reviewError.value = '驳回时必须填写原因。'; return }
  reviewSubmitting.value = true; reviewError.value = ''
  try {
    const decision = reviewDecision.value
    await resourceApi.reviewQuestion(selectedQuestion.value.question_id, decision, reviewComment.value)
    selectedQuestion.value = null; reviewMessage.value = decision === 'APPROVED' ? '题目已通过审核并发布。' : '题目已驳回并退回修改。'
    await load()
  } catch (reason) { reviewError.value = (reason as ApiError).message || '审核操作失败，请稍后重试。' }
  finally { reviewSubmitting.value = false }
}
onMounted(load); watch(page, load)
</script>

<template>
  <div class="resource-page">
    <YkPageHeader :title="titles[page][0]" :description="titles[page][1]"><template #actions><div v-if="page === 'questions'" class="actions"><button class="yk-button" @click="downloadQuestionTemplate">下载 XLSX（电子表格）模板</button><button class="yk-button primary" @click="openQuestionImport">批量导入题目</button></div><button v-if="page === 'audit'" class="yk-button primary" @click="runAudit">重新执行全量审计</button><button v-if="page === 'delivery'" class="yk-button primary" @click="freezeDelivery">冻结交付版本</button></template></YkPageHeader>
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
        <p v-if="questionImportError" class="status-error">{{ questionImportError }}</p>
        <p v-if="questionImportMessage" class="success-notice">{{ questionImportMessage }}</p>
        <p v-if="reviewMessage" class="success-notice">{{ reviewMessage }}</p>
        <YkTabs v-model="questionTab" :tabs="questionTabs" />
        <template v-if="questionTab === 'overview'">
          <div class="grid grid-4 summary-grid"><div class="card kpi"><span>课时总数</span><b>{{ coverage.length }}</b></div><div class="card kpi"><span>覆盖通过</span><b>{{ readiness?.question_lessons.ready || 0 }} / 49</b></div><div class="card kpi"><span>已审核发布题目</span><b>{{ readiness?.published_questions.ready || 0 }} / 196</b></div><div class="card kpi"><span>四种题型</span><b>填/单/多/判</b></div></div><div class="card table-card"><table class="data-table"><thead><tr><th>课时</th><th>已有题型</th><th>门禁</th></tr></thead><tbody><tr v-for="item in coverage" :key="item.lesson_id"><td>{{ item.lesson_code }}</td><td>{{ item.types.map(questionTypeText).join('、') || '尚无已审核题目' }}</td><td><span class="badge" :class="{ warn: !item.passed }">{{ item.passed ? '通过' : '阻断' }}</span></td></tr></tbody></table></div>
        </template>
        <template v-else-if="questionTab === 'import'">
          <div v-if="!questionImportJob" class="state-panel"><b>尚无本次导入结果</b><span>请先下载模板，按模板准备 196 行题目，再选择 XLSX（电子表格）文件导入。</span><div class="actions"><button class="yk-button" @click="downloadQuestionTemplate">下载模板</button><button class="yk-button primary" @click="openQuestionImport">选择文件并导入</button></div></div>
          <template v-else>
            <div class="card row-between"><div><b>{{ questionImportJob.original_filename || '题库导入文件' }}</b><p class="muted">处理状态：{{ importStatusText(questionImportJob.status) }}</p></div><div class="actions"><button class="yk-button" @click="refreshQuestionImportJob">刷新处理结果</button><button v-if="questionImportJob.error_count" class="yk-button" @click="downloadQuestionErrors">下载错误明细</button></div></div>
            <div class="grid grid-4 summary-grid"><div class="card kpi"><span>文件数据行</span><b>{{ questionImportJob.total_count }}</b></div><div class="card kpi"><span>导入成功</span><b>{{ questionImportJob.imported_count }}</b></div><div class="card kpi"><span>错误行</span><b>{{ questionImportJob.error_count }}</b></div><div class="card kpi"><span>进入待审核</span><b>{{ questionImportJob.review_queue_count }}</b></div></div>
            <div class="card table-card"><div class="section-head"><h3>逐行校验结果</h3><span class="badge" :class="{ warn: questionImportJob.error_count > 0 }">{{ questionImportJob.error_count ? `发现 ${questionImportJob.error_count} 行错误` : '全部数据行通过校验' }}</span></div><table v-if="questionImportJob.error_rows.length" class="data-table"><thead><tr><th>电子表格行号</th><th>字段</th><th>错误原因</th></tr></thead><tbody><tr v-for="item in questionImportJob.error_rows" :key="`${item.row_number}-${item.field}-${item.code}`"><td>{{ errorRowText(item.row_number) }}</td><td>{{ errorFieldText(item.field) }}</td><td>{{ item.message }}</td></tr></tbody></table><div v-else class="empty-cell">没有逐行错误，可以进入独立审核队列继续处理。</div></div>
          </template>
        </template>
        <template v-else>
          <div v-if="questionReviewLoading" class="state-panel">正在读取独立审核队列…</div>
          <div v-else class="card table-card"><div class="section-head"><h3>独立审核队列</h3><button class="yk-button" @click="loadQuestionReviewQueue">刷新队列</button></div><p v-if="reviewError" class="status-error">{{ reviewError }}</p><table class="data-table"><thead><tr><th>课时</th><th>题型</th><th>题干</th><th>提交人</th><th>来源</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="item in questionReviewItems" :key="item.question_id"><td>{{ item.lesson_code }}</td><td>{{ questionTypeText(item.question_type) }}</td><td>{{ item.stem }}</td><td>{{ questionCreatorText(item) }}</td><td>{{ item.source_row_number ? `电子表格第 ${item.source_row_number} 行` : '手工录入' }}</td><td><span class="badge warn">{{ statusText(item.status) }}</span></td><td><span v-if="isOwnQuestion(item)" class="status-error">需其他审核人</span><button v-else class="yk-button" @click="openQuestionReview(item)">审核</button></td></tr><tr v-if="!questionReviewItems.length"><td colspan="7" class="empty-cell">当前没有待审核题目。</td></tr></tbody></table></div>
        </template>
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
    <YkModal :open="questionImportOpen" title="批量导入题库" @close="questionImportOpen = false">
      <form class="form-grid" @submit.prevent="submitQuestionImport">
        <div class="wide"><b>导入 196 行题库数据</b><p class="muted">请使用本页下载的模板。系统逐行校验课时、题型、题干、选项、答案和解析，有效题目进入独立审核队列。</p></div>
        <label class="wide"><span>选择 XLSX（电子表格）文件</span><input class="input" aria-label="选择题库文件" type="file" accept=".xlsx" @change="selectQuestionFile" /></label>
        <p v-if="questionFile" class="wide">已选择：{{ questionFile.name }}</p>
        <p v-if="questionImportError" class="wide status-error">{{ questionImportError }}</p>
        <div class="wide actions"><button class="yk-button primary" type="submit" :disabled="questionImporting || !questionFile">{{ questionImporting ? '正在上传并逐行校验…' : '开始导入' }}</button><button class="yk-button" type="button" :disabled="questionImporting" @click="questionImportOpen = false">取消</button></div>
      </form>
    </YkModal>
    <YkDrawer :open="!!selectedQuestion" title="题目独立审核" @close="selectedQuestion = null">
      <form v-if="selectedQuestion" class="form-grid" @submit.prevent="submitQuestionReview">
        <div class="wide card"><div class="row-between"><b>{{ selectedQuestion.lesson_code }} · {{ questionTypeText(selectedQuestion.question_type) }}</b><span class="badge warn">{{ statusText(selectedQuestion.status) }}</span></div><h3>{{ selectedQuestion.stem }}</h3><ol v-if="selectedQuestion.options.length"><li v-for="option in selectedQuestion.options" :key="option.key">{{ option.key }}. {{ option.text }}</li></ol><p><b>答案：</b>{{ selectedQuestion.answer.join('、') }}</p><p><b>解析：</b>{{ selectedQuestion.explanation }}</p><p class="muted">提交人：{{ questionCreatorText(selectedQuestion) }}<span v-if="selectedQuestion.source_row_number"> · 来源：电子表格第 {{ selectedQuestion.source_row_number }} 行</span></p></div>
        <div class="wide actions" role="radiogroup" aria-label="审核结论"><YkRadio v-model="reviewDecision" value="APPROVED" label="通过并发布" /><YkRadio v-model="reviewDecision" value="REJECTED" label="驳回修改" /></div>
        <label class="wide"><span>{{ reviewDecision === 'REJECTED' ? '驳回原因（必填）' : '审核意见（选填）' }}</span><textarea v-model="reviewComment" class="input" rows="4" placeholder="请填写具体、可执行的审核意见"></textarea></label>
        <p v-if="reviewError" class="wide status-error">{{ reviewError }}</p>
        <div class="wide actions"><button class="yk-button primary" type="submit" :disabled="reviewSubmitting">{{ reviewSubmitting ? '正在提交审核…' : reviewDecision === 'APPROVED' ? '确认通过并发布' : '确认驳回' }}</button><button class="yk-button" type="button" :disabled="reviewSubmitting" @click="selectedQuestion = null">取消</button></div>
      </form>
    </YkDrawer>
  </div>
</template>
