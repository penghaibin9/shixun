<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import YkPageHeader from '../../components/common/YkPageHeader.vue'
import { downloadKnowledgeDiagram, listKnowledge, type ApiError } from '../api'

type Knowledge = { knowledge_point_id: string; title: string; explain_text: string; question_ids: string[]; diagrams: Array<{ diagram_id: string; file_id: string; title: string }> }
const items = ref<Knowledge[]>([])
const selectedId = ref('')
const loading = ref(true)
const error = ref('')
const diagramUrl = ref('')
const selected = computed(() => items.value.find(item => item.knowledge_point_id === selectedId.value) ?? items.value[0])
onMounted(async () => { try { items.value = await listKnowledge(); selectedId.value = items.value[0]?.knowledge_point_id ?? '' } catch (reason) { error.value = (reason as ApiError).message } finally { loading.value = false } })
watch(selected, async (item) => {
  if (diagramUrl.value) URL.revokeObjectURL(diagramUrl.value)
  diagramUrl.value = ''
  if (!item?.diagrams[0]) return
  try { diagramUrl.value = URL.createObjectURL(await downloadKnowledgeDiagram(item.knowledge_point_id, item.diagrams[0].diagram_id)) } catch (reason) { error.value = (reason as ApiError).message }
}, { immediate: true })
onBeforeUnmount(() => { if (diagramUrl.value) URL.revokeObjectURL(diagramUrl.value) })
async function download() {
  if (!selected.value?.diagrams[0]) return
  const blob = await downloadKnowledgeDiagram(selected.value.knowledge_point_id, selected.value.diagrams[0].diagram_id)
  const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'RSA 数字签名讲解图.svg'; anchor.click(); URL.revokeObjectURL(url)
}
</script>

<template>
  <YkPageHeader title="知识点讲解图" description="按知识点维护关联题目、讲解图和在线讲解文本。" />
  <div v-if="loading" class="card state-card">正在读取知识点…</div>
  <div v-else-if="error" class="card state-card error-state">{{ error }}</div>
  <div v-else-if="!selected" class="card state-card">当前课程还没有知识点讲解配置。</div>
  <div v-else class="knowledge-layout">
    <aside class="card"><h2>知识点列表</h2><button v-for="item in items" :key="item.knowledge_point_id" class="knowledge-item" :class="{ active: item.knowledge_point_id === selected.knowledge_point_id }" @click="selectedId = item.knowledge_point_id"><b>{{ item.title }}</b><small>{{ item.question_ids.length }} 道关联题目 · {{ item.diagrams.length }} 张讲解图</small></button></aside>
    <section class="card knowledge-stage"><div class="section-title"><h2>{{ selected.title }} · 在线讲解图</h2><button class="yk-button" :disabled="!diagramUrl" @click="download">下载讲解图</button></div><img v-if="diagramUrl" :src="diagramUrl" :alt="selected.diagrams[0]?.title" style="display:block;width:100%;height:auto" /><div v-else class="state-card">讲解图加载中…</div></section>
    <section class="card"><h2>讲解配置</h2><div class="yk-field"><label>关联题目</label><div v-for="question in selected.question_ids" :key="question" class="token">{{ question }}</div></div><div class="yk-field"><label>讲解图</label><p>{{ selected.diagrams[0]?.title ?? '尚未配置' }}</p></div><div class="yk-field"><label>讲解文本</label><p class="explain-text">{{ selected.explain_text }}</p></div></section>
  </div>
</template>
