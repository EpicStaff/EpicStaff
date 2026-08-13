import { DestroyRef, effect, inject, signal, WritableSignal } from '@angular/core';

const STORAGE_KEY_PREFIX = 'node-panel-column-width';
const PERSIST_DEBOUNCE_MS = 300;

export interface ColumnWidthState {
    readonly width: WritableSignal<number>;
    readonly defaultWidth: number;
}

/**
 * Width of a panel's resizable column, remembered per panel so a layout the user tuned survives
 * reopening the panel. Call it as a field initializer — it needs an injection context — and bind
 * `[style.flex-basis.px]="<state>.width()"` on the column left of the divider.
 */
export function createColumnWidthState(panelKey: string, defaultWidth: number): ColumnWidthState {
    const storageKey = `${STORAGE_KEY_PREFIX}:${panelKey}`;
    const storedWidth = readStoredWidth(storageKey);
    const width = signal(storedWidth ?? defaultWidth);
    let persistTimeout: ReturnType<typeof setTimeout> | undefined;
    let persistedWidth = storedWidth ?? defaultWidth;

    /**
     * Reads the signal rather than a captured value, so a panel closed before the effect runs still
     * stores its last width.
     */
    function persistWidth(): void {
        clearTimeout(persistTimeout);
        persistTimeout = undefined;
        const next = width();
        if (next === persistedWidth) {
            return;
        }
        writeStoredWidth(storageKey, next);
        persistedWidth = next;
    }

    effect(() => {
        // Read only to depend on it; persistWidth compares against what is stored, so this effect's
        // own first run writes nothing.
        width();
        clearTimeout(persistTimeout);
        persistTimeout = setTimeout(persistWidth, PERSIST_DEBOUNCE_MS);
    });

    inject(DestroyRef).onDestroy(persistWidth);

    return { width, defaultWidth };
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
