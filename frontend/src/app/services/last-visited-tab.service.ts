import { Injectable } from '@angular/core';

const STORAGE_KEY = 'lastVisitedTab';

/**
 * Remembers the last active child route for each parent route.
 * Persisted to localStorage so it survives navigation away and back.
 */
@Injectable({
    providedIn: 'root',
})
export class LastVisitedTabService {
    private load(): Record<string, string> {
        try {
            return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}');
        } catch {
            return {};
        }
    }

    set(parentPath: string, fullChildPath: string): void {
        const map = this.load();
        map[parentPath] = fullChildPath;
        localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
    }

    get(parentPath: string): string | null {
        return this.load()[parentPath] ?? null;
    }
}
