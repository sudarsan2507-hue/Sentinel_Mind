import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readdirSync, readFileSync, writeFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { gzipSync } from 'node:zlib'

// Write <file>.gz beside every text asset. Flask serves these when the browser
// accepts gzip (backend/app.py `_static`) -- compression at build time, zero
// cost per request. Uncompressed JS/CSS was the top Lighthouse finding.
// The app pages are lazy chunks, so a direct visit to /graph used to fetch the
// main script, run it, and only then discover the page chunk -- a second round
// trip before anything rendered. This writes a tiny inline script into
// index.html that starts fetching the right chunks for the URL being opened.
const ROUTES = { '/dashboard': 'src/pages/Dashboard.jsx', '/graph': 'src/pages/KnowledgeGraph.jsx' }

function routePreload() {
  return {
    name: 'route-preload',
    apply: 'build',
    writeBundle() {
      const manifest = JSON.parse(readFileSync('dist/.vite/manifest.json', 'utf8'))
      const files = (key, seen = new Set()) => {
        if (seen.has(key) || !manifest[key]) return []
        seen.add(key)
        const entry = manifest[key]
        return [entry.file, ...(entry.imports || []).flatMap((k) => files(k, seen))]
      }
      const entry = Object.keys(manifest).find((k) => manifest[k].isEntry)
      const shared = new Set(files(entry))
      const map = Object.fromEntries(Object.entries(ROUTES).map(([path, src]) => [
        path, files(src).filter((f) => !shared.has(f)),
      ]))
      const script = `<script>(function(){var p=location.pathname;if(p.length>1&&p.slice(-1)==='/')p=p.slice(0,-1);` +
        `var m=${JSON.stringify(map)}[p];` +
        `if(m)m.forEach(function(f){var l=document.createElement('link');l.rel='modulepreload';l.href='/'+f;document.head.appendChild(l)})})()</script>`
      const html = readFileSync('dist/index.html', 'utf8').replace('</head>', `  ${script}
</head>`)
      writeFileSync('dist/index.html', html)
    },
  }
}

function precompress() {
  return {
    name: 'precompress',
    apply: 'build',
    closeBundle() {
      const walk = (dir) => readdirSync(dir).forEach((f) => {
        const p = join(dir, f)
        if (statSync(p).isDirectory()) return walk(p)
        if (/\.(js|css|html|svg|json|txt)$/.test(f) && statSync(p).size > 1024) {
          writeFileSync(`${p}.gz`, gzipSync(readFileSync(p), { level: 9 }))
        }
      })
      walk('dist')
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), routePreload(), precompress()],
  build: { manifest: true },
  server: {
    proxy: {
      '/trace': { target: 'http://localhost:5000', changeOrigin: true },
      '/audit': { target: 'http://localhost:5000', changeOrigin: true },
      '/session': { target: 'http://localhost:5000', changeOrigin: true },
      '/knowledge': { target: 'http://localhost:5000', changeOrigin: true },
      '/health': { target: 'http://localhost:5000', changeOrigin: true },
      '/socket.io': {
        target: 'http://localhost:5000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
