import eslint from '@eslint/js';
import tseslint from 'typescript-eslint';

const typescriptFiles = ['**/*.ts', '**/*.tsx'];

export default [
  {
    ignores: ['dist/**', 'coverage/**', 'node_modules/**'],
  },
  {
    ...eslint.configs.recommended,
    files: typescriptFiles,
  },
  ...tseslint.configs.recommended.map((config) => ({
    ...config,
    files: typescriptFiles,
  })),
];
