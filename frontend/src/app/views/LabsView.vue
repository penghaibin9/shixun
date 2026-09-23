<script setup lang="ts">
import { onMounted, ref } from 'vue'
import YkPageHeader from '../../components/common/YkPageHeader.vue'
import { importLab, listLabs, type ApiError, type Lab } from '../api'

const labs = ref<Lab[]>([])
const loading = ref(true)
const importing = ref(false)
const showImport = ref(false)
const loadError = ref('')
const importError = ref('')
const importedMessage = ref('')
const importFile = ref<File | null>(null)
const importCode = ref('')
const importCategory = ref('综合实验')
const importObjective = ref('')
onMounted(async () => { try { labs.value = await listLabs() } catch (reason) { loadError.value = (reason as ApiError).message } finally { loading.value = false } })

function selectImportFile(event: Event) {
  importFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function submitImport() {
  if (!importFile.value || !importCode.value.trim() || !importObjective.value.trim()) {
    importError.value = '请选择实验定义文件，并填写实验编号和实验目标。'
    return
  }
  importing.value = true; importError.value = ''; importedMessage.value = ''
  try {
    const imported = await importLab(importFile.value, {
      course_id: localStorage.getItem('yk-course-id') || 'course_data_security',
      code: importCode.value.trim(),
      category: importCategory.value.trim(),
      objective: importObjective.value.trim(),
    })
    labs.value = [imported, ...labs.value]
    importedMessage.value = `已导入“${imported.name}”草稿，请完成校验后发布。`
    showImport.value = false
  } catch (reason) { importError.value = (reason as ApiError).message }
  finally { importing.value = false }
}
</script>

<template>
  <YkPageHeader title="实验中心" description="实验模板、场景、DAG、判分和发布共用同一份版本化实验定义。">
    <template #actions><div class="row"><button class="yk-button" @click="showImport = !showImport">导入实验配置</button><RouterLink class="yk-button primary" to="/lab-builder">＋ 创建实验</RouterLink></div></template>
  </YkPageHeader>
  <div v-if="importedMessage" class="notice success-notice">{{ importedMessage }}</div>
  <form v-if="showImport" class="card form-grid" @submit.prevent="submitImport">
    <div v-if="importError" class="wide notice error-state">{{ importError }}</div>
    <label>实验定义 JSON（数据文本）<input class="input" type="file" accept="application/json,.json" @change="selectImportFile" /></label>
    <label>实验编号<input v-model="importCode" class="input" maxlength="64" placeholder="例如：EXP-DS-13" /></label>
    <label>实验分类<input v-model="importCategory" class="input" maxlength="64" /></label>
    <label class="wide">实验目标<textarea v-model="importObjective" class="input" rows="3" maxlength="4000" /></label>
    <div class="wide row"><button class="yk-button primary" type="submit" :disabled="importing">{{ importing ? '正在校验并导入…' : '校验并导入草稿' }}</button><button class="yk-button" type="button" @click="showImport = false">取消</button></div>
  </form>
  <div v-if="loading" class="card state-card">正在读取实验定义…</div>
  <div v-else-if="loadError" class="card state-card error-state">{{ loadError }}</div>
  <div v-else-if="!labs.length" class="card state-card">当前课程还没有实验定义。</div>
  <div v-else class="grid grid-3">
    <article v-for="lab in labs" :key="lab.lab_definition_id" class="card lab-card">
      <h2>{{ lab.name }}</h2>
      <template v-if="lab.latest_version">
        <span class="badge" :class="lab.latest_version.status === 'PUBLISHED' ? 'success' : ''">{{ lab.latest_version.status === 'PUBLISHED' ? '已发布' : '草稿' }}</span>
        <p class="muted">{{ lab.latest_version.spec.nodes.length }} 个节点 · {{ lab.latest_version.spec.steps.length }} 步 · {{ lab.latest_version.spec.checkpoints.length }} 个得分点 · {{ lab.latest_version.spec.total_score }} 分</p>
      </template>
      <p v-else class="muted">尚未创建实验版本，请先进入设计页完成定义。</p>
      <RouterLink class="yk-button primary" :to="`/lab-builder?lab=${lab.lab_definition_id}`">查看设计</RouterLink>
    </article>
  </div>
</template>
