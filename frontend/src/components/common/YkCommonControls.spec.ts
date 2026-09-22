import { mount } from '@vue/test-utils'
import { defineComponent, nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'

import YkCheck from './YkCheck.vue'
import YkDrawer from './YkDrawer.vue'
import YkModal from './YkModal.vue'
import YkRadio from './YkRadio.vue'
import YkSelect from './YkSelect.vue'
import YkToast from './YkToast.vue'

describe('公共控件无障碍交互', () => {
  it('将外部标签绑定到下拉触发器，并支持方向键与回车选择', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const wrapper = mount(YkSelect, {
      attachTo: host,
      props: {
        modelValue: 'a',
        options: [{ label: '甲', value: 'a' }, { label: '乙', value: 'b' }],
        'aria-label': '发布状态',
      },
    })
    const trigger = wrapper.get('.yk-select-trigger')
    expect(trigger.attributes('aria-label')).toBe('发布状态')
    trigger.element.focus()
    await trigger.trigger('keydown', { key: 'ArrowDown' })
    await nextTick()
    const options = wrapper.findAll('[role="option"]')
    expect(options).toHaveLength(2)
    expect(document.activeElement).toBe(options[1].element)
    await options[1].trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['b'])
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
    wrapper.unmount()
    host.remove()
  })

  it('公开复选和单选的语义状态，并能在单选组中用方向键切换', async () => {
    const check = mount(YkCheck, { props: { modelValue: false, label: '选择学生' } })
    expect(check.get('[role="checkbox"]').attributes('aria-checked')).toBe('false')
    expect(check.get('[role="checkbox"]').attributes('aria-label')).toBe('选择学生')
    await check.get('[role="checkbox"]').trigger('click')
    expect(check.emitted('update:modelValue')?.[0]).toEqual([true])

    const RadioHarness = defineComponent({
      components: { YkRadio },
      setup() { return { value: ref('approved') } },
      template: '<div role="radiogroup" aria-label="审核结论"><YkRadio v-model="value" value="approved" label="通过"/><YkRadio v-model="value" value="rejected" label="驳回"/></div>',
    })
    const host = document.createElement('div')
    document.body.appendChild(host)
    const radios = mount(RadioHarness, { attachTo: host })
    const items = radios.findAll('[role="radio"]')
    expect(items[0].attributes('aria-checked')).toBe('true')
    await items[0].trigger('keydown', { key: 'ArrowRight' })
    await nextTick()
    expect(items[1].attributes('aria-checked')).toBe('true')
    expect(document.activeElement).toBe(items[1].element)
    radios.unmount()
    host.remove()
  })

  it.each([
    ['弹窗', YkModal, '.yk-modal'],
    ['抽屉', YkDrawer, '.yk-drawer'],
  ])('%s 会约束焦点，Escape 关闭后恢复到触发元素', async (_name, Dialog, selector) => {
    const Harness = defineComponent({
      components: { Dialog },
      setup() { return { open: ref(false) } },
      template: '<button data-testid="trigger" @click="open=true">打开</button><Dialog :open="open" title="详情" @close="open=false"><button data-testid="inside">内容操作</button></Dialog>',
    })
    const host = document.createElement('div')
    document.body.appendChild(host)
    const wrapper = mount(Harness, { attachTo: host })
    const trigger = wrapper.get('[data-testid="trigger"]')
    trigger.element.focus()
    await trigger.trigger('click')
    await nextTick()
    const dialog = wrapper.get(selector)
    const close = dialog.get('button[aria-label="关闭"]')
    const inside = dialog.get('[data-testid="inside"]')
    expect(dialog.attributes('role')).toBe('dialog')
    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(document.activeElement).toBe(close.element)
    inside.element.focus()
    await inside.trigger('keydown', { key: 'Tab' })
    expect(document.activeElement).toBe(close.element)
    await dialog.trigger('keydown', { key: 'Escape' })
    await nextTick()
    expect(wrapper.find(selector).exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
    wrapper.unmount()
    host.remove()
  })

  it('将提示消息放入礼貌播报区域', () => {
    const wrapper = mount(YkToast, { props: { messages: [{ id: 'one', text: '已保存' }] } })
    expect(wrapper.attributes('role')).toBe('status')
    expect(wrapper.attributes('aria-live')).toBe('polite')
    expect(wrapper.attributes('aria-atomic')).toBe('true')
    expect(wrapper.text()).toContain('已保存')
  })
})
