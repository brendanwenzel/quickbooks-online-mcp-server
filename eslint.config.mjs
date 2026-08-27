import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: ['coverage/**', 'dist/**', 'node_modules/**'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{js,mjs,cjs,ts}'],
    languageOptions: {
      globals: {
        ...globals.node,
        ...globals.jest,
      },
    },
  },
  {
    files: ['**/*.ts'],
    rules: {
      // This established codebase uses `any` at the dynamic QuickBooks SDK
      // boundary. Enabling this rule would turn initial ESLint adoption into a
      // multi-thousand-line unrelated refactor.
      '@typescript-eslint/no-explicit-any': 'off',
      // As with `any`, this is pre-existing debt across the generated tool
      // surface. Keep ESLint executable now without bundling unrelated churn;
      // a future type-cleanup can enable it incrementally by directory.
      '@typescript-eslint/no-unused-vars': 'off',
    },
  },
);
