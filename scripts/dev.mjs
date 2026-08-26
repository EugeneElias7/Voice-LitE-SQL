// Voice-LitE-SQL -- Level 11: start the FastAPI backend and Vite frontend
// together for local development. Run with:  npm run dev
import { spawn } from 'node:child_process'

const isWindows = process.platform === 'win32'
const shell = isWindows ? true : false

const children = []

function start(name, command, args) {
  const child = spawn(command, args, { shell, stdio: 'inherit' })
  children.push(child)
  console.log(`[${name}] starting: ${command} ${args.join(' ')}`)
  child.on('exit', (code) => {
    console.log(`[${name}] exited with code ${code}`)
    shutdown()
  })
}

function shutdown() {
  for (const child of children) {
    try {
      child.kill()
    } catch {
      /* already gone */
    }
  }
  process.exit(0)
}

process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)

start('backend', 'python', ['-m', 'uvicorn', 'backend.api.main:app', '--host', '127.0.0.1', '--port', '8000'])
start('frontend', 'npm', ['--prefix', 'frontend', 'run', 'dev'])

console.log('\nVoice-LitE-SQL dev servers:')
console.log('  backend  -> http://127.0.0.1:8000')
console.log('  frontend -> http://localhost:5173\n')