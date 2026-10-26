// Builds the Weather page into dist/: type-checks, bundles src/main.ts and src/styles.css with content-hashed names
// (index.html is served with no-cache, everything else may be cached), and writes index.html pointing at them.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { build } from 'esbuild';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, 'dist');
const require = createRequire(import.meta.url);

const sdkEntry = join(root, 'node_modules', '@epicstaff', 'plugin-sdk', 'dist', 'index.js');
if (!existsSync(sdkEntry)) {
    console.error(
        'The EpicStaff JS SDK is not built. Run: npm --prefix plugin-sdk ci && npm --prefix plugin-sdk run build'
    );
    process.exit(1);
}

execFileSync(process.execPath, [require.resolve('typescript/bin/tsc'), '--noEmit', '-p', join(root, 'tsconfig.json')], {
    stdio: 'inherit',
});

rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });

const result = await build({
    absWorkingDir: root,
    entryPoints: { app: 'src/main.ts', styles: 'src/styles.css' },
    bundle: true,
    format: 'esm',
    target: 'es2022',
    minify: true,
    sourcemap: false,
    legalComments: 'none',
    entryNames: '[name]-[hash]',
    outdir: outDir,
    metafile: true,
    logLevel: 'warning',
});

const outputFor = (entryPoint) => {
    const output = Object.entries(result.metafile.outputs).find(([, meta]) => meta.entryPoint === entryPoint);
    if (!output) throw new Error(`esbuild wrote no output for ${entryPoint}`);
    return `/${basename(output[0])}`;
};

const html = readFileSync(join(root, 'src', 'index.html'), 'utf8')
    .replace('%APP_SCRIPT%', outputFor('src/main.ts'))
    .replace('%APP_STYLES%', outputFor('src/styles.css'));
writeFileSync(join(outDir, 'index.html'), html);

console.log(`Built the Weather page into ${outDir}`);
