import { Injectable, signal } from '@angular/core';

export type DeskRailMode = 'list' | 'compact';

const STORAGE_KEY = 'chat:deskRailMode';
const DEFAULT_MODE: DeskRailMode = 'list';

/**
 * The desk rail mode the user picked, remembered per browser. Root-provided so that, when storage is unavailable, the
 * choice still holds in memory after leaving the chat area and coming back (which recreates the rail).
 */
@Injectable({ providedIn: 'root' })
export class DeskRailModeService {
    private readonly modeSignal = signal<DeskRailMode>(this.readStoredMode());
    readonly mode = this.modeSignal.asReadonly();

    setMode(mode: DeskRailMode): void {
        this.modeSignal.set(mode);
        try {
            localStorage.setItem(STORAGE_KEY, mode);
        } catch {
            // localStorage unavailable (quota exceeded, private mode): the mode still holds in memory.
        }
    }

    private readStoredMode(): DeskRailMode {
        let stored: string | null;
        try {
            stored = localStorage.getItem(STORAGE_KEY);
        } catch {
            return DEFAULT_MODE;
        }
        return stored === 'list' || stored === 'compact' ? stored : DEFAULT_MODE;
    }
}
