export default [{
  files: ["src/typed_graph/adapters/static/*.js"],
  languageOptions: {
    ecmaVersion: 2022,
    sourceType: "module",
    globals: {
      window: "readonly", document: "readonly", EventSource: "readonly",
      fetch: "readonly", console: "readonly", setTimeout: "readonly",
      clearTimeout: "readonly", navigator: "readonly", URL: "readonly",
      Blob: "readonly", requestAnimationFrame: "readonly", location: "readonly",
      sessionStorage: "readonly", CSS: "readonly", AbortController: "readonly", IntersectionObserver: "readonly"
    }
  },
  rules: {
    "no-undef": "error",
    "no-unused-vars": ["error", {"argsIgnorePattern": "^_"}],
    "no-constant-condition": "error",
    "no-dupe-args": "error",
    "no-dupe-keys": "error",
    "no-unreachable": "error",
    "valid-typeof": "error",
    "eqeqeq": "error"
  }
}];
