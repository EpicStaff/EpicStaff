import { Injectable, Signal, signal, WritableSignal } from '@angular/core';

const STORAGE_PREFIX = 'sidebar-width:';
const DEFAULT_WIDTH = 360;
const DEFAULT_MIN_WIDTH = 220;
const DEFAULT_MAX_WIDTH = 600;

@Injectable({
    providedIn: 'root',
})
export class SidebarWidthService {
    private readonly widthSignals = new Map<string, WritableSignal<number>>();

    public getWidth(
        key: string,
        defaultPx = DEFAULT_WIDTH,
        min = DEFAULT_MIN_WIDTH,
        max = DEFAULT_MAX_WIDTH
    ): Signal<number> {
        return this.getOrCreateSignal(key, defaultPx, min, max).asReadonly();
    }

    public setWidth(key: string, px: number, min: number, max: number): void {
        const clamped = this.clamp(px, min, max);
        this.getOrCreateSignal(key, clamped, min, max).set(clamped);
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

    private getOrCreateSignal(key: string, defaultPx: number, min: number, max: number): WritableSignal<number> {
        let existing = this.widthSignals.get(key);
        if (!existing) {
            existing = signal(this.readStoredWidth(key, defaultPx, min, max));
            this.widthSignals.set(key, existing);
        }
        return existing;
    }

    private readStoredWidth(key: string, defaultPx: number, min: number, max: number): number {
        let raw: string | null = null;
        try {
            raw = localStorage.getItem(STORAGE_PREFIX + key);
        } catch {
            return defaultPx;
        }
        if (raw == null) {
            return defaultPx;
        }
        const parsed = Number(raw);
        return Number.isFinite(parsed) ? this.clamp(parsed, min, max) : defaultPx;
    }

    private clamp(px: number, min: number, max: number): number {
        return Math.min(max, Math.max(min, Math.round(px)));
    }
}
