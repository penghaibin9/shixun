import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ContentLibraryView from './ContentLibraryView.vue'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('内容包中心', () => {
  it('把外部靶场的许可证和运行门禁直接展示给教师', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path.endsWith('/api/v1/content-packs')) return json({ items: [] })
      if (path.endsWith('/api/v1/content-sources')) return json({ items: [] })
      if (path.includes('/external-runtime/contracts')) {
        return json({
          version: '1.0.0',
          rule: '外部项目不能绕过许可证、镜像摘要、Linux Node Agent 与教师预演。',
          items: [
            {
              source_name: 'OWASP Juice Shop',
              license_id: 'MIT',
              license_decision: 'ALLOW',
              license_reason: '允许保留声明后使用',
              integration_mode: 'ISOLATED_TARGET_SERVICE',
              source_compose_execution_allowed: false,
              external_frontend_embedding_allowed: false,
              required_gates: ['LICENSE_PASS', 'COMPOSE_SAFETY_PASS', 'IMAGE_DIGEST_FROZEN', 'LINUX_NODE_AGENT_PASS', 'TEACHER_PREVIEW_PASS', 'CHECKPOINT_PASS'],
              current_status: 'EXTERNAL_IMAGE_REQUIRED',
              notes: ['独立 target 服务'],
            },
            {
              source_name: 'WebGoat',
              license_id: 'GPL-2.0-or-later',
              license_decision: 'REVIEW',
              license_reason: '商业交付前必须复核',
              integration_mode: 'ISOLATED_TARGET_SERVICE',
              source_compose_execution_allowed: false,
              external_frontend_embedding_allowed: false,
              required_gates: ['LICENSE_REVIEW_PASS', 'COMPOSE_SAFETY_PASS', 'IMAGE_DIGEST_FROZEN', 'LINUX_NODE_AGENT_PASS', 'TEACHER_PREVIEW_PASS', 'CHECKPOINT_PASS'],
              current_status: 'LICENSE_REVIEW_REQUIRED',
              notes: [],
            },
          ],
        })
      }
      if (path.includes('/lab-candidates')) return json({ labs: [] })
      if (path.includes('/content-source-maps/seed')) return json({ domain_map: [] })
      throw new Error(`unexpected request: ${path}`)
    }))

    const wrapper = mount(ContentLibraryView)
    await flushPromises()

    expect(wrapper.text()).toContain('外部靶场接入门禁')
    expect(wrapper.text()).toContain('OWASP Juice Shop')
    expect(wrapper.text()).toContain('独立隔离靶场')
    expect(wrapper.text()).toContain('EXTERNAL_IMAGE_REQUIRED')
    expect(wrapper.text()).toContain('WebGoat')
    expect(wrapper.text()).toContain('LICENSE_REVIEW_REQUIRED')
    expect(wrapper.text()).toContain('IMAGE_DIGEST_FROZEN → LINUX_NODE_AGENT_PASS → TEACHER_PREVIEW_PASS')
    expect(wrapper.text()).toContain('禁止')
  })
})
