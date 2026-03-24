import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';
import { fileURLToPath, URL } from 'node:url';
import path from 'node:path';

const __dirname = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  plugins: [preact()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '#docs': fileURLToPath(new URL('..', import.meta.url)),
    }
  },
  server: {
    port: 4173,
    fs: {
      allow: [path.resolve(__dirname, '..')]
    }
  }
});
