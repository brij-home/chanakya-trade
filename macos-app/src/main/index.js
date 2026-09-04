import { app, BrowserWindow, shell, ipcMain, Tray, nativeImage, globalShortcut } from 'electron'
import { join, resolve } from 'path'
import { existsSync } from 'fs'
import { spawn } from 'child_process'
import { ensurePythonEnv, VENV_PATH } from './pythonBootstrap.js'
import { rmSync } from 'fs'

const PORT = 8765

// ---------------------------------------------------------------------------
// Uvicorn sidecar
// ---------------------------------------------------------------------------
let uvicornProcess = null

async function waitForReady(port, ms = 15000) {
  const deadline = Date.now() + ms
  while (Date.now() < deadline) {
    try { const r = await fetch(`http://127.0.0.1:${port}/health`); if (r.ok) return true } catch (_) {}
    await new Promise(r => setTimeout(r, 400))
  }
  return false
}

async function startSidecar(venvBin, sourceRoot) {
  const isWin = process.platform === 'win32'
  const uvicornExec = isWin ? 'uvicorn.exe' : 'uvicorn'
  let uvicorn = join(venvBin, uvicornExec)
  if (!existsSync(uvicorn)) {
    uvicorn = join(venvBin, 'uvicorn')
  }
  
  if (!existsSync(uvicorn)) {
    // Fallback: run via python -m uvicorn
    const pyExec = isWin ? 'python.exe' : 'python'
    const py = join(venvBin, pyExec)
    if (!existsSync(py)) throw new Error(`uvicorn and python not found at ${venvBin}`)
    uvicornProcess = spawn(py, ['-m', 'uvicorn', 'web.api:app', '--host', '127.0.0.1', '--port', String(PORT), '--log-level', 'warning'], {
      cwd: sourceRoot,
      env: { ...process.env, PYTHONPATH: sourceRoot, PATH: `${venvBin}${isWin ? ';' : ':'}${process.env.PATH}` },
    })
  } else {
    uvicornProcess = spawn(uvicorn, ['web.api:app', '--host', '127.0.0.1', '--port', String(PORT), '--log-level', 'warning'], {
      cwd: sourceRoot,
      env: { ...process.env, PYTHONPATH: sourceRoot, PATH: `${venvBin}${isWin ? ';' : ':'}${process.env.PATH}` },
    })
  }

  uvicornProcess.stderr.on('data', d => process.stdout.write(`[uvicorn] ${d}`))
  uvicornProcess.on('error', e => { throw new Error(e.message) })
  uvicornProcess.on('exit', code => { console.log('[uvicorn] exit', code); uvicornProcess = null })

  if (!await waitForReady(PORT)) throw new Error(`FastAPI server did not start within 15s on port ${PORT}`)
}

function stopSidecar() {
  if (uvicornProcess) { try { uvicornProcess.kill('SIGTERM') } catch (_) {}; uvicornProcess = null }
}

// ---------------------------------------------------------------------------
// Bootstrap: detect Python, create venv, install deps, start sidecar
// ---------------------------------------------------------------------------
async function bootstrapAndStart() {
  const sendProgress = (data) => mainWindow?.webContents.send('setup-progress', data)

  // Fast-path: If sidecar is ALREADY running on PORT (e.g. launched manually or background service), use it!
  try {
    const isAlreadyAlive = await waitForReady(PORT, 1200)
    if (isAlreadyAlive) {
      console.log(`[sidecar] Server already active on port ${PORT}`)
      _readyPort = PORT
      mainWindow?.webContents.send('sidecar-ready', { port: PORT })
      return
    }
  } catch (_) {}

  try {
    const { venvBin, sourceRoot } = await ensurePythonEnv((progress) => {
      sendProgress(progress)
    })

    sendProgress({ stage: 'starting', message: 'Starting server...' })
    await startSidecar(venvBin, sourceRoot)

    _readyPort = PORT
    mainWindow?.webContents.send('sidecar-ready', { port: PORT })
  } catch (err) {
    if (err.isPythonMissing) {
      mainWindow?.webContents.send('setup-python-missing', {
        message: err.message,
        installUrl: 'https://www.python.org/downloads/',
        brewCommand: 'brew install python@3.12',
      })
    } else {
      mainWindow?.webContents.send('sidecar-error', {
        message: err.message,
        details: err.stderr || '',
      })
    }
  }
}

// ---------------------------------------------------------------------------
// Tray
// ---------------------------------------------------------------------------
let tray = null

function createTray() {
  const iconPath = join(__dirname, '../../build/icon.iconset/icon_16x16.png')
  const icon     = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 })
  icon.setTemplateImage(true)

  tray = new Tray(icon)
  tray.setToolTip('ChanakyaTrade')
  tray.setTitle('◆')

  tray.on('click', () => {
    if (!mainWindow) return
    if (mainWindow.isVisible() && mainWindow.isFocused()) {
      mainWindow.hide()
    } else {
      mainWindow.show()
      mainWindow.focus()
    }
  })
}

// ---------------------------------------------------------------------------
// Window
// ---------------------------------------------------------------------------
let mainWindow = null

function validateExternalUrl(rawUrl) {
  let parsed
  try { parsed = new URL(String(rawUrl)) } catch { throw new Error('Invalid external URL') }
  if (parsed.protocol !== 'https:') throw new Error('Only HTTPS links can be opened externally')
  return parsed.toString()
}

function createWindow() {
  const appIcon = nativeImage.createFromPath(join(__dirname, '../../build/icon.iconset/icon_512x512.png'))
  if (process.platform === 'darwin' && appIcon && !appIcon.isEmpty()) {
    app.dock.setIcon(appIcon)
  }

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    icon: appIcon,
    backgroundColor: '#0d0d0d',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 18 },
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
    show: false,
  })

  if (!app.isPackaged) {
    mainWindow.loadURL('http://localhost:5173')
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
    bootstrapAndStart()
  })

  mainWindow.on('closed', () => { mainWindow = null })
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    try { shell.openExternal(validateExternalUrl(url)) } catch (_) {}
    return { action: 'deny' }
  })
}

// ---------------------------------------------------------------------------
// IPC
// ---------------------------------------------------------------------------
let _readyPort = null

ipcMain.handle('get-port', () => _readyPort)
ipcMain.handle('open-external', (_, url) => shell.openExternal(validateExternalUrl(url)))
ipcMain.handle('sidecar-request', async (_, request = {}) => {
  const method = String(request.method || 'GET').toUpperCase()
  const endpoint = String(request.endpoint || '')
  if (!['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    throw new Error('Unsupported API method')
  }
  if (!endpoint.startsWith('/') || endpoint.startsWith('//') || endpoint.includes('://')) {
    throw new Error('Invalid API endpoint')
  }
  if (!_readyPort) {
    try {
      const check = await fetch(`http://127.0.0.1:${PORT}/health`)
      if (check.ok) _readyPort = PORT
    } catch (_) {}
  }
  if (!_readyPort) throw new Error('API is not ready')
  const allowedHeaders = {}
  for (const [key, value] of Object.entries(request.headers || {})) {
    if (['content-type', 'x-csrf-token'].includes(String(key).toLowerCase())) allowedHeaders[key] = String(value)
  }
  const body = request.body === undefined || method === 'GET' ? undefined : JSON.stringify(request.body)
  if (body && Buffer.byteLength(body, 'utf8') > 1_000_000) throw new Error('Request body exceeds 1 MB limit')

  const response = await fetch(`http://127.0.0.1:${_readyPort}${endpoint}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...allowedHeaders },
    body,
  })
  const text = await response.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  return { ok: response.ok, status: response.status, data }
})

ipcMain.on('update-tray', (_, { label }) => {
  if (tray) tray.setTitle(label ? ` ${label}` : '◆')
})

// Setup IPC: retry and reset
ipcMain.handle('retry-setup', async () => {
  _readyPort = null
  stopSidecar()
  await bootstrapAndStart()
})

ipcMain.handle('reset-venv', async () => {
  _readyPort = null
  stopSidecar()
  try { rmSync(VENV_PATH, { recursive: true, force: true }) } catch (_) {}
  await bootstrapAndStart()
})

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
app.whenReady().then(() => {
  if (!app.isPackaged) {
    app.setName('ChanakyaTrade')
  }

  createTray()
  createWindow()

  globalShortcut.register('CommandOrControl+Shift+Space', () => {
    if (!mainWindow) return
    if (mainWindow.isVisible() && mainWindow.isFocused()) {
      mainWindow.hide()
    } else {
      mainWindow.show()
      mainWindow.focus()
    }
  })
})

app.on('before-quit', () => {
  globalShortcut.unregisterAll()
  stopSidecar()
})
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') { stopSidecar(); app.quit() }
})
