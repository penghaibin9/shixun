import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import YkSelect from './YkSelect.vue'

describe('YkSelect', () => {
  it('通过键盘和点击选择值', async () => {
    const wrapper = mount(YkSelect, { props: { modelValue: 'a', options: [{ label: '甲', value: 'a' }, { label: '乙', value: 'b' }] } })
    await wrapper.get('.yk-select-trigger').trigger('click')
    await wrapper.findAll('[role="option"]')[1].trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['b'])
  })
})
