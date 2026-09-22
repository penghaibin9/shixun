<script setup lang="ts">
import { onMounted, ref } from 'vue'
import YkPageHeader from '../../components/common/YkPageHeader.vue'
import { listTemplates, type ApiError } from '../api'

type Template = { template_id: string; name: string; description: string; spec: Record<string, unknown> }
const templates = ref<Template[]>([])
const loading = ref(true)
const error = ref('')
onMounted(async () => { try { templates.value = await listTemplates() } catch (reason) { error.value = (reason as ApiError).message } finally { loading.value = false } })
function exampleLab(item: Template): string { return typeof item.spec.example_lab_definition_id === 'string' ? item.spec.example_lab_definition_id : 'lab_rsa' }
</script>

<template>
  <YkPageHeader title="实验模板库" description="老师优先从模板开始，场景与步骤仍可完整修改。" />
  <div v-if="loading" class="card state-card">正在读取模板…</div>
  <div v-else-if="error" class="card state-card error-state">{{ error }}</div>
  <div v-else-if="!templates.length" class="card state-card">当前没有可用模板。</div>
  <div v-else class="grid grid-3">
    <article v-for="item in templates" :key="item.template_id" class="card template-card">
      <span class="badge success">推荐</span><h2>{{ item.name }}</h2><p class="muted">{{ item.description }}</p>
      <RouterLink class="yk-button primary" :to="`/lab-builder?lab=${exampleLab(item)}`">查看模板示例定义</RouterLink>
    </article>
  </div>
</template>

