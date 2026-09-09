import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'

// Seamless HMR auto-recovery: If Fast Refresh fails to hot-patch in-place,
// reload cleanly so code edits always reflect immediately without manual refreshes.
if (import.meta.hot) {
  import.meta.hot.on('vite:error', () => {
    window.location.reload()
  })
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary title="ChanakyaTrade Application">
      <App />
    </ErrorBoundary>
  </React.StrictMode>
)
