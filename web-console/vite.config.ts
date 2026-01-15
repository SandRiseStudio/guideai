import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: (() => {
      const candidates = [
        process.env.GUIDEAI_REPO_ROOT,
        resolve(__dirname, '..'),
        resolve(__dirname),
      ].filter(Boolean) as string[];

      for (const base of candidates) {
        const srcEntry = resolve(base, 'packages/collab-client/src/index.ts');
        const distEntry = resolve(base, 'packages/collab-client/dist/index.js');
        if (existsSync(srcEntry)) {
          return { '@guideai/collab-client': srcEntry };
        }
        if (existsSync(distEntry)) {
          return { '@guideai/collab-client': distEntry };
        }
      }

      return {};
    })(),
  },
  server: {
    fs: {
      allow: [
        ...(process.env.GUIDEAI_REPO_ROOT ? [resolve(process.env.GUIDEAI_REPO_ROOT)] : []),
        resolve(__dirname, '..'),
        resolve(__dirname),
      ],
    },
  },
});
