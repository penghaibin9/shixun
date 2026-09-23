import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { importLab, listLabs } = vi.hoisted(() => ({
  importLab: vi.fn(),
  listLabs: vi.fn(),
}))
vi.mock('../api', () => ({ importLab, listLabs }))

import LabsView from './LabsView.vue'

const lab = {
  lab_definition_id: 'lab_aes_des', course_id: 'course_data_security', lesson_id: 'lesson_lab_01',
  code: 'EXP-DS-01', name: 'AES/DES 基础加解密', category: '密码学', objective: '目标',
  latest_version: { status: 'PUBLISHED', spec: { nodes: [{}, {}], steps: [{}, {}, {}, {}, {}, {}], checkpoints: [{}, {}, {}, {}, {}], total_score: 100 } },
}

describe('实验总览', () => {
  beforeEach(() => {
    listLabs.mockReset().mockResolvedValue([lab])
    importLab.mockReset().mockResolvedValue({ ...lab, lab_definition_id: 'lab_imported', name: '导入实验', latest_version: { ...lab.latest_version, status: 'DRAFT' } })
  })

  it('展示数据库实验并可把导出的 JSON 数据文本重新导入为草稿', async () => {
    const wrapper = mount(LabsView, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()
    expect(wrapper.text()).toContain('AES/DES 基础加解密')
    await wrapper.get('button').trigger('click')
    const inputs = wrapper.findAll('input')
    const file = new File(['{"lab_definition_id":"lab_imported"}'], 'lab.json', { type: 'application/json' })
    Object.defineProperty(inputs[0].element, 'files', { value: [file] })
    await inputs[0].trigger('change')
    await inputs[1].setValue('EXP-IMPORT-01')
    await wrapper.get('textarea').setValue('验证导入回环。')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(importLab).toHaveBeenCalledWith(file, expect.objectContaining({ code: 'EXP-IMPORT-01', objective: '验证导入回环。' }))
    expect(wrapper.text()).toContain('已导入“导入实验”草稿')
  })

  it('实验尚无版本时展示安全空态而不读取空版本字段', async () => {
    listLabs.mockResolvedValueOnce([{ ...lab, latest_version: null }])
    const wrapper = mount(LabsView, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()

    expect(wrapper.text()).toContain('尚未创建实验版本，请先进入设计页完成定义。')
  })

  it('导入失败时保留已有实验列表并在表单内显示错误', async () => {
    importLab.mockRejectedValueOnce({ message: '实验定义格式不正确' })
    const wrapper = mount(LabsView, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()
    await wrapper.get('button').trigger('click')
    const inputs = wrapper.findAll('input')
    const file = new File(['{}'], 'bad.json', { type: 'application/json' })
    Object.defineProperty(inputs[0].element, 'files', { value: [file] })
    await inputs[0].trigger('change')
    await inputs[1].setValue('EXP-BAD-01')
    await wrapper.get('textarea').setValue('验证失败反馈。')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('实验定义格式不正确')
    expect(wrapper.text()).toContain('AES/DES 基础加解密')
  })
})
