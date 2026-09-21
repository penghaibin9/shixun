<script setup lang="ts">
import { onMounted, ref } from 'vue'
import YkPageHeader from '../../components/common/YkPageHeader.vue'
import { listLabs, type ApiError, type Lab } from '../api'

const labs = ref<Lab[]>([])
const loading = ref(true)
const error = ref('')
onMounted(async () => { try { labs.value = await listLabs() } catch (reason) { error.value = (reason as ApiError).message } finally { loading.value = false } })
</script>

<template>
  <YkPageHeader title="实验中心" description="实验模板、场景、DAG、判分和发布共用同一份版本化实验定义。">
    <template #actions><RouterLink class="yk-button primary" to="/lab-builder">＋ 创建实验</RouterLink></template>
  </YkPageHeader>
  <div v-if="loading" class="card state-card">正在读取实验定义…</div>
  <div v-else-if="error" class="card state-card error-state">{{ error }}</div>
  <div v-else-if="!labs.length" class="card state-card">当前课程还没有实验定义。</div>
  <div v-else class="grid grid-3">
    <article v-for="lab in labs" :key="lab.lab_definition_id" class="card lab-card">
      <span class="badge" :class="lab.latest_version.status === 'PUBLISHED' ? 'success' : ''">{{ lab.latest_version.status === 'PUBLISHED' ? '已发布' : '草稿' }}</span>
      <h2>{{ lab.name }}</h2>
      <p class="muted">{{ lab.latest_version.spec.nodes.length }} 个节点 · {{ lab.latest_version.spec.steps.length }} 步 · {{ lab.latest_version.spec.checkpoints.length }} 个得分点 · {{ lab.latest_version.spec.total_score }} 分</p>
      <RouterLink class="yk-button primary" :to="`/lab-builder?lab=${lab.lab_definition_id}`">查看设计</RouterLink>
    </article>
  </div>
</template>
