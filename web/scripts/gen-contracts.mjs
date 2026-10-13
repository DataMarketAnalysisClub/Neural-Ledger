// Generates TypeScript types from the JSON Schemas in ../contracts (the source of truth).
// Run after any contract change: `npm run contracts`. The output is committed so the build
// does not depend on the generator.
import { compileFromFile } from "json-schema-to-typescript";
import { mkdir, readdir, writeFile } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const contracts = resolve(here, "../../contracts");
const out = resolve(here, "../src/contracts");

async function* schemas(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* schemas(path);
    else if (entry.name.endsWith(".schema.json")) yield path;
  }
}

const banner = "/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */";
let count = 0;
for await (const file of schemas(contracts)) {
  const rel = relative(contracts, file).replace(/\.schema\.json$/, ".ts");
  const ts = await compileFromFile(file, { cwd: dirname(file), bannerComment: banner, additionalProperties: false, ignoreMinAndMaxItems: true, format: true });
  const target = join(out, rel);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, ts);
  count += 1;
}
console.log(`Generated ${count} contract types into ${relative(process.cwd(), out)}`);
