import { defineConfig, loadEnv, type ViteDevServer, type PreviewServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import tailwindcss from '@tailwindcss/vite';
import { cp, stat, readFile } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { resolve, extname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('.', import.meta.url));
const runtime = resolve(root, 'node_modules/cesium/Build/Cesium');

async function getLocalToken(): Promise<string | null> {
  const candidates = [
    resolve(root, '.cesium-token.local'),
    resolve(root, '../../sunlight-viewer/.cesium-token.local'),
    resolve(root, '../.cesium-token.local'),
  ];
  for (const candidate of candidates) {
    try {
      const content = (await readFile(candidate, 'utf8')).trim();
      if (content) return content;
    } catch {
      // try next candidate
    }
  }
  return null;
}

function cesiumToken(server: ViteDevServer | PreviewServer) {
  server.middlewares.use(async (request, response, next) => {
    const pathname = new URL(request.url || '/', 'http://localhost').pathname;
    if (pathname === '/api/cesium-token') {
      response.setHeader('Content-Type', 'application/json; charset=utf-8');
      response.setHeader('Cache-Control', 'no-store');
      const token = await getLocalToken();
      if (token) {
        response.end(JSON.stringify({ token }));
      } else {
        response.statusCode = 404;
        response.end(JSON.stringify({ error: 'local token missing' }));
      }
      return;
    }
    next();
  });
}

function cesiumAssets(server: ViteDevServer | PreviewServer) {
  server.middlewares.use(async (request, response, next) => {
    const pathname = new URL(request.url || '/', 'http://localhost').pathname;
    if (!pathname.startsWith('/cesium/')) return next();
    try {
      const path = resolve(runtime, decodeURIComponent(pathname.slice(8)));
      if (!path.startsWith(runtime + sep) || !(await stat(path)).isFile()) return next();
      const mime: Record<string, string> = { '.js': 'text/javascript', '.json': 'application/json', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml', '.wasm': 'application/wasm' };
      response.setHeader('Content-Type', mime[extname(path)] || 'application/octet-stream');
      createReadStream(path).pipe(response);
    } catch { next(); }
  });
}
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, root, '');
  return {
    plugins: [vue(), tailwindcss(), {
      name: 'cesium-local-assets', configureServer: (server) => { cesiumToken(server); cesiumAssets(server); },
      configurePreviewServer: (server) => { cesiumToken(server); cesiumAssets(server); },
      async closeBundle() { await cp(runtime, resolve(root, 'dist/cesium'), { recursive: true }); },
    }],
    server: { port: 5178, strictPort: true, proxy: { '/api/v1': { target: env.API_PROXY_TARGET || 'http://127.0.0.1:8001', changeOrigin: true } } },
    preview: { port: 5178, strictPort: true, proxy: { '/api/v1': { target: env.API_PROXY_TARGET || 'http://127.0.0.1:8001', changeOrigin: true } } },
  };
});
