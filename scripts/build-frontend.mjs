import { readFile, writeFile, mkdir } from "node:fs/promises";
import { resolve, basename } from "node:path";
import assert from "node:assert/strict";
const source = resolve("workmate/static");
const output = resolve("outputs/frontend-dist");
const assets = ["index.html", "styles.css", "app.js", "api.js", "formatters.js", "workspace.js"];
const html = await readFile(resolve(source, "index.html"), "utf8");
const version = html.match(/app\.js\?v=([^"\s]+)/)?.[1];
assert.ok(version, "HTML needs a versioned application module");
assert.ok(html.includes(`styles.css?v=${version}`), "CSS and JS versions must agree");
await mkdir(output, { recursive: true });
let bytes = 0;
for (const asset of assets) {
  const content = await readFile(resolve(source, asset));
  if (asset.endsWith(".js")) {
    for (const match of content.toString().matchAll(/from\s+["'](\.\/[^"']+)["']/g)) {
      const [path, query] = match[1].split("?");
      assert.ok(assets.includes(basename(path)), `Missing module ${path}`);
      assert.equal(query, `v=${version}`, `Stale import version in ${asset}`);
    }
  }
  await writeFile(resolve(output, asset), content);
  assert.deepEqual(await readFile(resolve(output, asset)), content);
  bytes += content.length;
}
console.log(`Static frontend built: ${assets.length} assets, ${bytes} bytes. HTML/CSS/JS only.`);
