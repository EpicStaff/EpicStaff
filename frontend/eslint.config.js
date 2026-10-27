// @ts-check
const tseslint = require('typescript-eslint');
const angularEslintPlugin = require('@angular-eslint/eslint-plugin');
const simpleImportSort = require('eslint-plugin-simple-import-sort');

/** How a guided tour is drawn stays behind TOUR_RENDERER_LOADER (core/guided-tour/renderer/tour-renderer.ts). */
const TOUR_RENDERER_IMPORTS = {
  group: ['@angular/cdk/overlay', '**/renderer/cdk', '**/renderer/cdk/**'],
  message: 'Tour definitions and the tour engine talk to the TourRenderer interface only, so the renderer can be replaced.',
};

module.exports = tseslint.config({
  ignores: ['**/node_modules/**', '**/dist/**'],
  files: ['**/*.ts'],
  languageOptions: {
    parser: tseslint.parser,
  },
  plugins: {
    '@typescript-eslint': tseslint.plugin,
    'simple-import-sort': simpleImportSort,
    '@angular-eslint': angularEslintPlugin,
  },
  rules: {
    // warn and error are legitimate — they surface real problems to whoever opens the console.
    // log is developer instrumentation and should not ship
    'no-console': ['error', { allow: ['warn', 'error'] }],
    '@typescript-eslint/no-explicit-any': 'error',
    '@typescript-eslint/no-unused-vars': 'error',
    'simple-import-sort/imports': 'error',
    'simple-import-sort/exports': 'error',
    '@angular-eslint/component-selector': ['error', { type: 'element', prefix: 'app', style: 'kebab-case' }],
    '@angular-eslint/directive-selector': ['error', { type: 'attribute', prefix: 'app', style: 'camelCase' }],
  },
}, {
  files: [
    'src/app/core/guided-tour/{engine,registry,progress,testing}/**/*.ts',
    'src/app/features/**/*.definition.ts',
  ],
  rules: {
    'no-restricted-imports': ['error', { patterns: [TOUR_RENDERER_IMPORTS] }],
  },
}, {
  // A renderer draws what the tour hands it through the TourRenderer seam; it never reaches back into the tour.
  files: ['src/app/core/guided-tour/renderer/cdk/**/*.ts'],
  rules: {
    'no-restricted-imports': [
      'error',
      {
        patterns: [
          {
            group: ['**/engine', '**/engine/**', '**/registry', '**/registry/**', '**/progress', '**/progress/**'],
            message: 'The CDK renderer knows the tour only through renderer/tour-renderer.ts and the model.',
          },
        ],
      },
    ],
  },
}, {
  // The tour contract: data shapes only, so anything may depend on it.
  files: ['src/app/core/guided-tour/model/**/*.ts'],
  rules: {
    'no-restricted-imports': [
      'error',
      { patterns: [{ regex: '^(?!\\./)', message: 'The tour contract imports only its own model files.' }] },
    ],
  },
});
