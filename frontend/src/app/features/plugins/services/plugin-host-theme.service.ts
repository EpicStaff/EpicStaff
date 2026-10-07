import { DOCUMENT } from '@angular/common';
import { DestroyRef, inject, Injectable, signal } from '@angular/core';

import { BridgeTheme } from '../bridge/bridge-protocol';

/** The class that switches EpicStaff to its light theme, on `<html>` or `<body>`. */
export const LIGHT_THEME_CLASS = 'my-app-light';

/**
 * The design tokens a bridge v2 plugin page gets, and the EpicStaff variable each one reads.
 * A stable public set: add tokens, never rename or remove one — plugin styles depend on the names.
 */
export const PLUGIN_THEME_TOKENS: Readonly<Record<string, string>> = Object.freeze({
    '--es-color-background': '--color-background-body',
    '--es-color-surface': '--color-surface-card',
    '--es-color-surface-raised': '--color-modals-background',
    '--es-color-sidenav': '--color-sidenav-background',
    '--es-color-text': '--color-text-primary',
    '--es-color-text-secondary': '--color-text-secondary',
    '--es-color-text-tertiary': '--color-text-tertiary',
    '--es-color-text-disabled': '--color-text-disabled',
    '--es-color-accent': '--accent-color',
    '--es-color-accent-hover': '--accent-color-hover',
    '--es-color-accent-active': '--accent-color-active',
    '--es-color-input-background': '--color-input-background',
    '--es-color-input-border': '--color-input-border',
    '--es-color-input-placeholder': '--color-input-text-placeholder',
    '--es-color-border': '--color-border',
    '--es-color-divider': '--color-divider-regular',
    '--es-color-divider-subtle': '--color-divider-subtle',
    '--es-color-success': '--success-color',
    '--es-color-warning': '--color-warning',
    '--es-color-error': '--color-status-error',
    '--es-focus-ring': '--focus-ring',
    '--es-font-family': '--font-family',
});

/**
 * EpicStaff's current theme as plugin pages see it: `light` when `<html>` or `<body>` carries
 * {@link LIGHT_THEME_CLASS}, else `dark`, and the {@link PLUGIN_THEME_TOKENS} resolved on `<body>`.
 *
 * Re-read whenever the `class` attribute of `<html>` or `<body>` changes; `theme` only changes
 * when the mode or a token value really did, so unrelated classes (an open dialog's scroll block)
 * never reach a plugin page. A token EpicStaff doesn't define is left out, so the page's own
 * fallback applies.
 */
@Injectable({ providedIn: 'root' })
export class PluginHostThemeService {
    private readonly document = inject(DOCUMENT);

    private readonly themeSignal = signal<BridgeTheme>(this.readTheme(), { equal: isSameTheme });
    public readonly theme = this.themeSignal.asReadonly();

    constructor() {
        const view = this.document.defaultView;
        if (!view || typeof view.MutationObserver !== 'function') return;
        const observer = new view.MutationObserver(() => this.refresh());
        for (const element of [this.document.documentElement, this.document.body]) {
            if (element) observer.observe(element, { attributes: true, attributeFilter: ['class'] });
        }
        inject(DestroyRef).onDestroy(() => observer.disconnect());
    }

    /** Reads the theme again; a no-op for subscribers when nothing changed. */
    refresh(): void {
        this.themeSignal.set(this.readTheme());
    }

    private readTheme(): BridgeTheme {
        const root = this.document.documentElement;
        const body = this.document.body ?? root;
        const isLight = root.classList.contains(LIGHT_THEME_CLASS) || body.classList.contains(LIGHT_THEME_CLASS);
        const style = this.document.defaultView?.getComputedStyle(body);
        const tokens: Record<string, string> = {};
        for (const [token, source] of Object.entries(PLUGIN_THEME_TOKENS)) {
            const value = style?.getPropertyValue(source).trim() ?? '';
            if (value !== '') tokens[token] = value;
        }
        return { mode: isLight ? 'light' : 'dark', tokens };
    }
}

function isSameTheme(first: BridgeTheme, second: BridgeTheme): boolean {
    if (first.mode !== second.mode) return false;
    const firstEntries = Object.entries(first.tokens);
    return (
        firstEntries.length === Object.keys(second.tokens).length &&
        firstEntries.every(([token, value]) => second.tokens[token] === value)
    );
}
