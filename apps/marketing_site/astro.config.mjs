import { defineConfig } from 'astro/config';
import solidJs from '@astrojs/solid-js';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  integrations: [solidJs()],
  vite: {
    plugins: [tailwindcss()],
  },
});
