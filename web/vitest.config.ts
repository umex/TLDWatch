import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Vitest jsdom config for the FE test suite (VALIDATION.md Wave 0).
// The react plugin transforms TSX so component tests render under jsdom.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    css: false,
  },
})