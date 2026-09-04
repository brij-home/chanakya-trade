/**
 * useShallowSelector — Zustand selector with shallow equality.
 *
 * Prevents unnecessary re-renders when selecting objects/arrays from the store.
 * Wraps the Zustand `shallow` comparator so every consumer uses it consistently.
 *
 * Usage:
 *   // Instead of:
 *   const { brokerStatus, port } = useChatStore(s => ({ brokerStatus: s.brokerStatus, port: s.port }))
 *   // Use:
 *   const { brokerStatus, port } = useShallowSelector(s => ({ brokerStatus: s.brokerStatus, port: s.port }))
 */

import { shallow } from 'zustand/shallow'
import { useChatStore } from '../store/chatStore'

export function useShallowSelector(selector) {
  return useChatStore(selector, shallow)
}

/**
 * useInspectorShallow — Shallow selector for inspectorStore.
 */
import { useInspectorStore } from '../store/inspectorStore'

export function useInspectorShallow(selector) {
  return useInspectorStore(selector, shallow)
}
