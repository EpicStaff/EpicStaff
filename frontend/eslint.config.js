// @ts-check
const tseslint = require('typescript-eslint');
const angularEslintPlugin = require('@angular-eslint/eslint-plugin');
const simpleImportSort = require('eslint-plugin-simple-import-sort');

module.exports = tseslint.config({
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
    '@typescript-eslint/no-explicit-any': 'error',
    'simple-import-sort/imports': 'error',
    'simple-import-sort/exports': 'error',
    '@angular-eslint/component-selector': ['error', { type: 'element', prefix: 'app', style: 'kebab-case' }],
    '@angular-eslint/directive-selector': ['error', { type: 'attribute', prefix: 'app', style: 'camelCase' }],
  },
});
