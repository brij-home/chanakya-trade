import { create } from 'zustand'
import { METRIC_ENCYCLOPEDIA } from '../data/metricEncyclopedia'

export { METRIC_ENCYCLOPEDIA }

export const useInspectorStore = create((set) => ({
  isOpen: false,
  activeMetric: null,
  contextData: null,

  openInspector: (metricKeyOrConfig, contextData = null) => {
    if (typeof metricKeyOrConfig === 'string') {
      const predefined = METRIC_ENCYCLOPEDIA[metricKeyOrConfig] || {
        title: metricKeyOrConfig.replace(/_/g, ' ').toUpperCase(),
        category: 'Market Metric',
        explanation: 'Institutional indicator used for financial and quantitative analysis.',
        institutionalGuide: 'Analyze in confluence with price action and risk parameters.',
      }
      set({
        isOpen: true,
        activeMetric: { key: metricKeyOrConfig, ...predefined },
        contextData,
      })
    } else {
      set({
        isOpen: true,
        activeMetric: metricKeyOrConfig,
        contextData,
      })
    }
  },

  closeInspector: () => set({ isOpen: false, activeMetric: null, contextData: null }),
}))
