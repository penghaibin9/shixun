import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'
import RuntimeAdminView from './RuntimeAdminView.vue'

vi.mock('../api', () => ({
  runtimeOverview: vi.fn(async () => ({ nodes_ready: 1, running_instances: 2, failed_instances: 0, destroyed_instances: 1, queued_groups: 0 })),
  runtimeNodes: vi.fn(async () => [{ node_id: 'n1', name: '计算节点 01', status: 'READY', scheduling_paused: false, weight: 100, cpu_total: 8, memory_total_mb: 8192, last_seen_at: '2026-09-21T10:00:00', capacity: { cpu_available: 6, memory_available_mb: 6144, running_groups: 2, image_digests: [] } }]),
  runtimeImages: vi.fn(async () => []), runtimeInstances: vi.fn(async () => []), runtimeQueue: vi.fn(async () => []),
  runtimeEvents: vi.fn(async () => [{ event_type: 'runtime.instance.started', runtime_instance_id: 'rti_1', detail: {}, occurred_at: '2026-09-21T10:00:00' }]),
}))

describe('运行时管理页面', () => {
  it('从接口事实渲染节点资源和中文状态', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/admin/nodes', component: RuntimeAdminView }] })
    await router.push('/admin/nodes'); await router.isReady()
    const wrapper = mount(RuntimeAdminView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('服务器节点')
    expect(wrapper.text()).toContain('计算节点 01')
    expect(wrapper.text()).toContain('就绪')
    expect(wrapper.text()).toContain('6.0 / 8.0 核可用')
  })
})
