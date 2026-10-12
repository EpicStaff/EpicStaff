import { Injectable, Signal, signal, WritableSignal } from '@angular/core';

const STORAGE_PREFIX = 'sidebar-width:';
const DEFAULT_WIDTH = 360;
const DEFAULT_MIN_WIDTH = 220;
const DEFAULT_MAX_WIDTH = 600;

/** Lets a sidebar collapse to a fixed narrow width instead of stopping at its minimum width. */
export interface SidebarCollapseOptions {
    /** Width of the collapsed sidebar. */
    collapsedWidth: number;
    /** A requested width below this collapses the sidebar; at or above it the sidebar is at least `minWidth`. */
    collapseThreshold: number;
}

export interface SidebarWidthOptions {
    defaultWidth?: number;
    minWidth?: number;
    maxWidth?: number;
    /** Without it the width is only clamped to `minWidth`..`maxWidth`. */
    collapse?: SidebarCollapseOptions | null;
}

@Injectable({
    providedIn: 'root',
})
export class SidebarWidthService {
    private readonly widthSignals = new Map<string, WritableSignal<number>>();

    public getWidth(key: string, options: SidebarWidthOptions = {}): Signal<number> {
        return this.getOrCreateSignal(key, options).asReadonly();
    }

    /** Sets the width, snapped to the allowed widths: the collapsed width or a width within the bounds. */
    public setWidth(key: string, width: number, options: SidebarWidthOptions = {}): void {
        const normalizedWidth = this.normalizeWidth(width, options);
        this.getOrCreateSignal(key, options).set(normalizedWidth);
    }

    public commitWidth(key: string): void {
        const value = this.widthSignals.get(key)?.();
        if (value == null) {
            return;
        }
        try {
            localStorage.setItem(STORAGE_PREFIX + key, String(value));
        } catch {
            // localStorage unavailable (quota exceeded, private mode) — width still holds in memory.
        }
    }

    private getOrCreateSignal(key: string, options: SidebarWidthOptions): WritableSignal<number> {
        let existing = this.widthSignals.get(key);
        if (!existing) {
            existing = signal(this.readStoredWidth(key, options));
            this.widthSignals.set(key, existing);
        }
        return existing;
    }

    private readStoredWidth(key: string, options: SidebarWidthOptions): number {
        const defaultWidth = options.defaultWidth ?? DEFAULT_WIDTH;
        let raw: string | null = null;
        try {
            raw = localStorage.getItem(STORAGE_PREFIX + key);
        } catch {
            return defaultWidth;
        }
        if (raw == null) {
            return defaultWidth;
        }
        const parsed = Number(raw);
        return Number.isFinite(parsed) ? this.normalizeWidth(parsed, options) : defaultWidth;
    }

    private normalizeWidth(width: number, options: SidebarWidthOptions): number {
        const roundedWidth = Math.round(width);
        if (options.collapse && roundedWidth < options.collapse.collapseThreshold) {
            return options.collapse.collapsedWidth;
        }
        const minWidth = options.minWidth ?? DEFAULT_MIN_WIDTH;
        const maxWidth = options.maxWidth ?? DEFAULT_MAX_WIDTH;
        return Math.min(maxWidth, Math.max(minWidth, roundedWidth));
    }
}
