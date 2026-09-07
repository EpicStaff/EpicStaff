import { Injectable, Signal, signal, WritableSignal } from '@angular/core';

const STORAGE_PREFIX = 'section-height:';

@Injectable({
    providedIn: 'root',
})
export class SectionHeightService {
    private readonly heightSignals = new Map<string, WritableSignal<number | null>>();

    public getHeight(key: string): Signal<number | null> {
        return this.getOrCreateSignal(key).asReadonly();
    }

    public setHeight(key: string, px: number, min: number, max: number): void {
        this.getOrCreateSignal(key).set(this.clamp(px, min, max));
    }

    public commitHeight(key: string): void {
        const value = this.heightSignals.get(key)?.();
        if (value == null) {
            return;
        }
        try {
            localStorage.setItem(STORAGE_PREFIX + key, String(value));
        } catch {
            // localStorage unavailable (quota exceeded, private mode) — height still holds in memory.
        }
    }

    private getOrCreateSignal(key: string): WritableSignal<number | null> {
        let existing = this.heightSignals.get(key);
        if (!existing) {
            existing = signal(this.readStoredHeight(key));
            this.heightSignals.set(key, existing);
        }
        return existing;
    }

    private readStoredHeight(key: string): number | null {
        let raw: string | null = null;
        try {
            raw = localStorage.getItem(STORAGE_PREFIX + key);
        } catch {
            return null;
        }
        if (raw == null) {
            return null;
        }
        const parsed = Number(raw);
        return Number.isFinite(parsed) ? parsed : null;
    }

    private clamp(px: number, min: number, max: number): number {
        return Math.min(max, Math.max(min, Math.round(px)));
    }
}
