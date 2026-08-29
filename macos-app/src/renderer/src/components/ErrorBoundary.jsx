import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught error:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center p-8 bg-panel border border-border/80 rounded-2xl text-center space-y-4 m-4">
          <div className="w-12 h-12 rounded-full bg-rose-500/15 border border-rose-500/30 flex items-center justify-center text-xl text-rose-400">
            ⚠️
          </div>
          <div>
            <h3 className="text-sm font-bold text-text font-mono">
              {this.props.title || 'Component Encountered an Issue'}
            </h3>
            <p className="text-xs text-muted max-w-md mt-1 font-ui">
              {this.state.error?.message || 'A rendering error occurred in this workspace.'}
            </p>
          </div>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-4 py-1.5 rounded-xl bg-amber text-black font-bold text-xs uppercase tracking-wide cursor-pointer hover:brightness-110 shadow-sm transition-all"
          >
            ↻ Recover View
          </button>
        </div>
      )
    }

    return this.props.children
  }
}
