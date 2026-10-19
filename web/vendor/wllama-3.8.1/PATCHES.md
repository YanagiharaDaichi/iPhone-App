# Local changes to @wllama/wllama 3.8.1

`index.js` is `esm/index.js` from the npm package, with one change:

- `isSafariMobile()` also returns true for any iPhone/iPad/iPod user agent. Web apps opened
  from the Home Screen on iOS report a user agent without "Safari", so wllama's iOS-specific
  code paths (no transferable buffers in worker messages) would otherwise be skipped there.

`wllama.wasm` and `../wllama-compat-3.8.1/*` (from @wllama/wllama-compat 3.8.1) are unchanged.
