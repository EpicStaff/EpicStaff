import { Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';

const STORAGE_KEY = 'epicstaff.activeOrgId';

@Injectable({
    providedIn: 'root',
})
export class ActiveOrgService implements StorageService {
    private readonly _activeOrgId = signal<number | null>(null);
    readonly activeOrgId = this._activeOrgId.asReadonly();

    constructor() {
        const cached = localStorage.getItem(STORAGE_KEY);
        if (cached) {
            const parsed = Number(cached);
            if (Number.isFinite(parsed)) this._activeOrgId.set(parsed);
        }
    }

    set(orgId: number | null): void {
        this._activeOrgId.set(orgId);
        if (orgId === null) {
            localStorage.removeItem(STORAGE_KEY);
        } else {
            localStorage.setItem(STORAGE_KEY, String(orgId));
        }
    }

    clear(): void {
        this.set(null);
    }
}
