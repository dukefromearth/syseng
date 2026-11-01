import {readFile, writeFile} from "node:fs/promises";
import process from "node:process";
import {Buffer} from "node:buffer";
import {createRequire} from "node:module";
import {build} from "esbuild";

const check = process.argv.includes("--check");
const result = await build({
  entryPoints: ["scripts/reader-diagrams.js"],
  outfile: "src/typed_graph/adapters/static/reader-diagrams.js",
  bundle: true,
  minify: true,
  format: "iife",
  globalName: "TypedGraphDiagrams",
  target: ["es2022"],
  legalComments: "linked",
  charset: "utf8",
  write: false,
});
// Mermaid Tiny ships a classic browser script, not an ESM/CommonJS module.
// Preserve its top-level global initialization rather than wrapping it in a module.
const require = createRequire(import.meta.url);
const mermaid = await readFile(require.resolve("@mermaid-js/tiny"));
for (const output of result.outputFiles) {
  const bytes = output.path.endsWith(".LEGAL.txt") ? output.contents
    : Buffer.concat([mermaid, Buffer.from("\n"), output.contents]);
  if (check) {
    const existing = await readFile(output.path);
    if (!existing.equals(bytes)) {
      throw new Error("Reader bundle is stale. Run npm run build:reader and commit its outputs.");
    }
  } else await writeFile(output.path, bytes);
}
