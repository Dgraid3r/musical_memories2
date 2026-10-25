// Extends vitest's `expect` with jest-dom's DOM matchers (toBeInTheDocument,
// toHaveTextContent, etc.) for every test file - loaded once via
// vitest.config.ts's `setupFiles` rather than imported per-test.
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// @testing-library/react's own auto-cleanup only self-registers against a
// *global* afterEach, which this project doesn't enable (vitest.config.ts
// sets test.globals: false so test files explicitly import what they use,
// matching this repo's usual style) - so each rendered component tree is
// unmounted explicitly here instead, keeping one test's DOM from leaking
// into the next.
afterEach(() => {
  cleanup()
})
