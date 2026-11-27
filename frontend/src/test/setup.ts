import '@testing-library/jest-dom/vitest'
import * as matchers from '@testing-library/jest-dom/matchers'

// The import above adds the matcher types, but the package's own vitest entry extends the
// `expect` exported by 'vitest', which is not the global `expect` the tests call. Register the
// matchers on the global one too.
expect.extend(matchers)
