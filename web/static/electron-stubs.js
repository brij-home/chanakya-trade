// Electron API stubs for web mode
// When running as a web app (not inside Electron), provide no-op implementations
// so the React app doesn't crash on missing IPC bridges.
if (!window.electronAPI) {
  const currentPort = parseInt(window.location.port, 10) || 8765;
  window.electronAPI = {
    getPort: () => Promise.resolve(currentPort),
    openExternal: (url) => window.open(url, '_blank'),
    updateTray: () => {},
    onSidecarReady: (cb) => { setTimeout(() => cb({ port: currentPort }), 0); },
    onSidecarError: (cb) => {},
    onSetupProgress: (cb) => {},
    onSetupPythonMissing: (cb) => {},
    retrySetup: () => Promise.resolve(),
    resetVenv: () => Promise.resolve(),
  }
}
window.__CHANAKYA_TRADE_WEB__ = true
