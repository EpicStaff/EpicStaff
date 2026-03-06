/**
 * Default Ruff configuration for the Python code editor.
 * See https://docs.astral.sh/ruff/settings
 */
export const RUFF_DEFAULT_CONFIG = {
  'line-length': 88,
  'indent-width': 4,
  format: {
    'indent-style': 'space',
    'quote-style': 'double',
  },
  lint: {
    select: ['E', 'W', 'F', 'I', 'N', 'UP', 'B', 'C4', 'SIM'],
    ignore: [],
  },
} as const;
