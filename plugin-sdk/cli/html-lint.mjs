// @ts-check
/**
 * Flags HTML that the plugin sandbox will break: its CSP is `script-src 'self'` (no inline code)
 * and `base-uri 'none'`, and it allows no outside network. A lint over the raw text, not a parser:
 * it errs towards reporting.
 *
 * @typedef {import('./bundle-files.mjs').Problem} Problem
 */

/** `<script type>` values that run as JavaScript (an empty type is classic script). */
const SCRIPT_TYPES = new Set([
    '',
    'module',
    'importmap',
    'speculationrules',
    'text/javascript',
    'application/javascript',
    'application/ecmascript',
    'text/ecmascript',
]);

/** Attributes that make the browser fetch something. */
const FETCHING_ATTRIBUTES = new Set(['src', 'href', 'srcset', 'poster', 'data', 'action', 'formaction']);
/** Tags whose `href` is a fetch (an `<a href>` is a navigation, not a fetch). */
const FETCHING_HREF_TAGS = new Set(['link', 'image', 'use']);

const COMMENT = /<!--[\s\S]*?-->/g;
const SCRIPT_ELEMENT = /<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi;
const START_TAG = /<([a-zA-Z][a-zA-Z0-9-]*)(\s[^>]*)?>/g;
const ATTRIBUTE = /([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;
const OUTSIDE_URL = /^\s*(?:[a-z][a-z0-9+.-]*:)?\/\//i;

/**
 * @param {string} html
 * @param {string} loc  the zip path, used in every problem
 * @returns {Problem[]}
 */
export function lintHtml(html, loc) {
    /** @type {Problem[]} */
    const problems = [];
    const text = html.replace(COMMENT, '');

    for (const match of text.matchAll(SCRIPT_ELEMENT)) {
        const attributes = parseAttributes(match[1] ?? '');
        const type = (attributes.get('type') ?? '').trim().toLowerCase();
        if ((match[2] ?? '').trim() !== '' && SCRIPT_TYPES.has(type)) {
            problems.push({
                level: 'error',
                loc,
                message:
                    "has an inline <script>; the sandbox runs only script files (script-src 'self'). Move the code into a .js file.",
            });
        }
    }

    for (const match of text.matchAll(START_TAG)) {
        const tag = (match[1] ?? '').toLowerCase();
        const attributes = parseAttributes(match[2] ?? '');
        if (tag === 'base') {
            problems.push({
                level: 'warning',
                loc,
                message:
                    "has a <base> element; the sandbox ignores it (base-uri 'none'). Relative URLs already resolve against the plugin's folder, so remove it.",
            });
        }
        for (const [name, value] of attributes) {
            if (/^on[a-z]/.test(name)) {
                problems.push({
                    level: 'error',
                    loc,
                    message: `has an inline event handler (${name}=) on <${tag}>; the sandbox blocks it. Add the listener from a script file.`,
                });
            }
            if (/^\s*javascript:/i.test(value)) {
                problems.push({
                    level: 'error',
                    loc,
                    message: `has a javascript: URL in ${name}= on <${tag}>; the sandbox blocks it.`,
                });
            }
            const fetches = FETCHING_ATTRIBUTES.has(name) && (name !== 'href' || FETCHING_HREF_TAGS.has(tag));
            if (fetches && OUTSIDE_URL.test(value)) {
                problems.push({
                    level: 'warning',
                    loc,
                    message: `loads ${value.trim().slice(0, 80)} from outside the plugin; the sandbox blocks all outside network. Bundle it instead.`,
                });
            }
        }
    }
    return problems;
}

/**
 * @param {string} source  the attribute part of a start tag
 * @returns {Map<string, string>}  lower-cased names; a bare attribute has the value ""
 */
function parseAttributes(source) {
    /** @type {Map<string, string>} */
    const attributes = new Map();
    for (const match of source.matchAll(ATTRIBUTE)) {
        const name = (match[1] ?? '').toLowerCase();
        if (name === '' || attributes.has(name)) continue;
        attributes.set(name, match[2] ?? match[3] ?? match[4] ?? '');
    }
    return attributes;
}
