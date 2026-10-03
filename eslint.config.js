import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';

const rules = {
  'no-undef': 'error',
  'no-unused-vars': ['error', { args: 'none', caughtErrors: 'none' }],
  'no-duplicate-imports': 'error',
};

export default [{ ignores: ['ui/dist/**', 'ui/dist-*/**'] }, {
  files: ['tests/frontend/**/*.js', 'playwright.config.js', 'ui/vite.config.js'],
  languageOptions: { globals: { ...globals.browser, ...globals.node } },
  rules,
}, {
  // The web UI (React).
  files: ['ui/src/**/*.{js,jsx}'],
  languageOptions: {
    globals: globals.browser,
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
  plugins: { 'react-hooks': reactHooks },
  rules: {
    ...rules,
    // JSX references don't count as uses for the core rule.
    'no-unused-vars': ['error', { args: 'none', caughtErrors: 'none', varsIgnorePattern: '^[A-Z]' }],
    ...reactHooks.configs.recommended.rules,
  },
}];
