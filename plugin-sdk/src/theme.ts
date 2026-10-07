import type { ThemeMode, ThemeState } from './protocol.js';

const TOKEN_NAME = /^--es-[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** Tokens set on each document, so a token EpicStaff stops sending is removed again. */
const appliedTokens = new WeakMap<Document, ReadonlySet<string>>();

/**
 * Applies EpicStaff's theme to `<html>`: every `--es-*` token as a CSS custom property,
 * `data-es-theme="dark|light"` and `color-scheme`. Use the tokens with a fallback, for example
 * `color: var(--es-color-text, #d9d9de)`, so the app also looks right outside EpicStaff.
 */
export function applyTheme(document: Document, theme: ThemeState): void {
    const root = document.documentElement;
    const previous = appliedTokens.get(document) ?? new Set<string>();
    const next = new Set<string>();
    for (const [name, value] of Object.entries(theme.tokens ?? {})) {
        if (!TOKEN_NAME.test(name) || typeof value !== 'string') continue;
        root.style.setProperty(name, value);
        next.add(name);
    }
    for (const name of previous) {
        if (!next.has(name)) root.style.removeProperty(name);
    }
    appliedTokens.set(document, next);

    const mode = normalizeThemeMode(theme.mode);
    root.setAttribute('data-es-theme', mode);
    root.style.setProperty('color-scheme', mode);
}

export function normalizeThemeMode(mode: unknown): ThemeMode {
    return mode === 'light' ? 'light' : 'dark';
}
