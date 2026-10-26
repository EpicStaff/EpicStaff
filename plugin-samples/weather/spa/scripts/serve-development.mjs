// Serves the Weather page from src/ for development (`npm run dev`), for EpicStaff to show on the plugin's own host
// while a SuperAdmin has set "Frontend dev server port" on the plugin's Development tab.
//
//   HOST  the address to listen on, default 127.0.0.1 (an IP address or localhost). On Linux, listen on the Docker
//         bridge address so EpicStaff's containers can reach it.
//   PORT  default 5173, from 1024 to 65535.
//
// The same entry points as build.mjs, bundled without hashing or minifying and rebuilt on every change. Every path
// without a file answers index.html, so the page's own routes load. The page reloads itself after each rebuild,
// through esbuild's change events on the page's own origin. Type errors are printed, never fatal. Nothing is written
// into dist/: the files live in a temporary directory, removed on exit.
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { isIP } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { context } from 'esbuild';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);

const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 5173;
const LOWEST_PORT = 1024;
const HIGHEST_PORT = 65535;
const LIVE_RELOAD_SCRIPT = 'esbuild-live-reload.js';

function usageError(message) {
    console.error(message);
    process.exit(2);
}

const host = process.env.HOST || DEFAULT_HOST;
if (host !== 'localhost' && isIP(host) === 0) usageError(`HOST must be an IP address or localhost, not "${host}".`);

const portText = process.env.PORT || String(DEFAULT_PORT);
const port = Number(portText);
if (!/^[0-9]+$/.test(portText) || port < LOWEST_PORT || port > HIGHEST_PORT) {
    usageError(`PORT must be a whole number from ${LOWEST_PORT} to ${HIGHEST_PORT}, not "${portText}".`);
}

const sdkEntry = join(root, 'node_modules', '@epicstaff', 'plugin-sdk', 'dist', 'index.js');
if (!existsSync(sdkEntry)) {
    console.error(
        'The EpicStaff JS SDK is not built. Run: npm --prefix plugin-sdk ci && npm --prefix plugin-sdk run build'
    );
    process.exit(1);
}

const serveDir = mkdtempSync(join(tmpdir(), 'weather-page-development-'));

// The page as build.mjs writes it, with unhashed names and the live reload, which is a file of this server: a page
// policy that allows only the page's own scripts still runs it.
const html = readFileSync(join(root, 'src', 'index.html'), 'utf8')
    .replace('%APP_SCRIPT%', '/app.js')
    .replace('%APP_STYLES%', '/styles.css')
    .replace(/^(\s*)<\/body>/m, `$1    <script src="/${LIVE_RELOAD_SCRIPT}"></script>\n$1</body>`);
writeFileSync(join(serveDir, 'index.html'), html);
writeFileSync(
    join(serveDir, LIVE_RELOAD_SCRIPT),
    "// Reloads the page after each rebuild of the development server.\nnew EventSource('/esbuild').addEventListener('change', () => location.reload());\n"
);

const typeChecker = spawn(
    process.execPath,
    [
        require.resolve('typescript/bin/tsc'),
        '--noEmit',
        '--watch',
        '--preserveWatchOutput',
        '-p',
        join(root, 'tsconfig.json'),
    ],
    { stdio: 'inherit' }
);

const builds = await context({
    absWorkingDir: root,
    entryPoints: { app: 'src/main.ts', styles: 'src/styles.css' },
    bundle: true,
    format: 'esm',
    target: 'es2022',
    minify: false,
    sourcemap: 'linked',
    legalComments: 'none',
    entryNames: '[name]',
    outdir: serveDir,
    logLevel: 'warning',
});

let stopping = false;
async function stop(exitCode) {
    if (stopping) return;
    stopping = true;
    typeChecker.kill();
    await builds.dispose();
    rmSync(serveDir, { recursive: true, force: true });
    process.exit(exitCode);
}
process.on('SIGINT', () => void stop(0));
process.on('SIGTERM', () => void stop(0));

try {
    await builds.watch();
    await builds.serve({ host, port, servedir: serveDir, fallback: join(serveDir, 'index.html') });
} catch (error) {
    console.error(`The development server could not start on ${host}:${port}: ${error.message}`);
    await stop(1);
}

console.log(`\nWeather page development server: http://${host}:${port}/`);
console.log(`Next: set Frontend dev server port ${port} in EpicStaff (Plugins → Weather → Development).`);
console.log('The page reloads after every change under src/. Press Ctrl-C to stop.\n');
