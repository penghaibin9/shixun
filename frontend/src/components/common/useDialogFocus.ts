import { nextTick, onBeforeUnmount, watch, type Ref } from 'vue'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function restoreFocus(target: HTMLElement | null) {
  if (target?.isConnected) target.focus()
}

/** 为公共模态层提供焦点进入、焦点约束、Escape 关闭和关闭后的焦点恢复。 */
export function useDialogFocus(
  isOpen: () => boolean,
  dialogRef: Ref<HTMLElement | null>,
  initialFocusRef: Ref<HTMLElement | null>,
  requestClose: () => void,
) {
  let previousFocus: HTMLElement | null = null

  watch(
    isOpen,
    async (open, wasOpen) => {
      if (typeof document === 'undefined') return
      if (open) {
        previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
        await nextTick()
        ;(initialFocusRef.value || dialogRef.value)?.focus()
      } else if (wasOpen) {
        restoreFocus(previousFocus)
        previousFocus = null
      }
    },
    { flush: 'post', immediate: true },
  )

  function onKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault()
      requestClose()
      return
    }
    if (event.key !== 'Tab') return

    const dialog = dialogRef.value
    if (!dialog) return
    const items = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
      (item) => item.getAttribute('aria-hidden') !== 'true',
    )
    if (!items.length) {
      event.preventDefault()
      dialog.focus()
      return
    }
    const current = document.activeElement as HTMLElement | null
    const index = current ? items.indexOf(current) : -1
    if (event.shiftKey && (index <= 0 || !current)) {
      event.preventDefault()
      items.at(-1)?.focus()
    } else if (!event.shiftKey && index === items.length - 1) {
      event.preventDefault()
      items[0]?.focus()
    }
  }

  onBeforeUnmount(() => restoreFocus(previousFocus))
  return { onKeydown }
}
