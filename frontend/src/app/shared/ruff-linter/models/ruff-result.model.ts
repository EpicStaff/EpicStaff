/**
 * Re-export Ruff Diagnostic type from the WASM package.
 * Used for type safety across the ruff-linter module.
 */
export type { Diagnostic as RuffDiagnostic } from '@astral-sh/ruff-wasm-web';
