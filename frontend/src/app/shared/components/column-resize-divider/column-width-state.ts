import { DestroyRef, inject, Signal, signal } from '@angular/core';

const STORAGE_KEY_PREFIX = 'node-panel-column-width';
const PERSIST_DEBOUNCE_MS = 300;

export interface ColumnWidthState {
    readonly width: Signal<number>;
    readonly defaultWidth: number;
    set(width: number): void;
}

/**
 * Width of a panel's resizable column, remembered per panel so a layout the user tuned survives
 * reopening the panel. Call it as a field initializer — it needs an injection context to store the
 * last width when the panel closes — and bind `[style.flex-basis.px]="<state>.width()"` on the
 * column left of the divider.
 */
export function createColumnWidthState(panelKey: string, defaultWidth: number): ColumnWidthState {
    const storageKey = `${STORAGE_KEY_PREFIX}:${panelKey}`;
    const width = signal(readStoredWidth(storageKey) ?? defaultWidth);
    let persistTimeout: ReturnType<typeof setTimeout> | undefined;
    let pendingWidth: number | null = null;

    function persistPendingWidth(): void {
        clearTimeout(persistTimeout);
        persistTimeout = undefined;
        if (pendingWidth === null) {
            return;
        }
        writeStoredWidth(storageKey, pendingWidth);
        pendingWidth = null;
    }

    inject(DestroyRef).onDestroy(persistPendingWidth);

    return {
        width: width.asReadonly(),
        defaultWidth,
        set(next: number): void {
            width.set(next);
            pendingWidth = next;
            clearTimeout(persistTimeout);
            persistTimeout = setTimeout(persistPendingWidth, PERSIST_DEBOUNCE_MS);
        },
    };
}

function readStoredWidth(storageKey: string): number | null {
    try {
        const raw = localStorage.getItem(storageKey);
        if (raw === null) {
            return null;
        }
        const parsed = Number(raw);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    } catch {
        return null;
    }
}

function writeStoredWidth(storageKey: string, width: number): void {
    try {
        localStorage.setItem(storageKey, String(width));
    } catch {
        // Storage unavailable (private mode, quota): the width still applies this session.
    }
}
