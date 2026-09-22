import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({
  listTemplates: vi.fn(async () => [
    { template_id: 'crypto', name: '双机密码学实验', description: '密码学', spec: { example_lab_definition_id: 'lab_rsa' } },
    { template_id: 'data', name: '数据处理实验', description: '数据处理', spec: { example_lab_definition_id: 'lab_base64' } },
    { template_id: 'database', name: '数据库访问控制实验', description: '数据库', spec: { example_lab_definition_id: 'lab_database_rbac' } },
  ]),
}))

import LabTemplatesView from './LabTemplatesView.vue'

describe('实验模板库', () => {
  it('三个正式模板分别打开对应的示例实验定义', async () => {
    const wrapper = mount(LabTemplatesView, {
      global: {
        stubs: {
          RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
          YkPageHeader: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.findAll('.template-card')).toHaveLength(3)
    expect(wrapper.findAll('a').map(link => link.attributes('href'))).toEqual([
      '/lab-builder?lab=lab_rsa',
      '/lab-builder?lab=lab_base64',
      '/lab-builder?lab=lab_database_rbac',
    ])
  })
})
