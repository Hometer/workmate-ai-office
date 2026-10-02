import globals from "globals";
const rules = {
  "no-undef": "error", "no-unused-vars": ["error", { caughtErrors: "none" }],
  "no-unreachable": "error", "no-dupe-keys": "error", "no-duplicate-imports": "error",
  "no-constant-condition": "error", "valid-typeof": "error", "use-isnan": "error",
  "no-irregular-whitespace": "error", "no-eval": "error", "no-new-func": "error"
};
export default [
  { files: ["workmate/static/*.js"], languageOptions: { globals: globals.browser }, rules },
  { files: ["scripts/*.mjs"], languageOptions: { globals: globals.node }, rules }
];
