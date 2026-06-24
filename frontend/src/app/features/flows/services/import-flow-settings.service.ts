import { Injectable, signal } from '@angular/core';

import { ImportFlowRequestOptions } from '../../../core/services/import-export.service';

export type ImportFlowSettings = ImportFlowRequestOptions;

const STORAGE_KEY = 'epicstaff.importFlowSettings';

const DEFAULT_SETTINGS: ImportFlowSettings = {
    preserveUuids: false,
    replaceExisting: false,
    importLabels: true,
};

@Injectable({ providedIn: 'root' })
export class ImportFlowSettingsService {
    private readonly _settings = signal<ImportFlowSettings>(this.load());
    public readonly settings = this._settings.asReadonly();

    public update(patch: Partial<ImportFlowSettings>): void {
        const next = { ...this._settings(), ...patch };
        this._settings.set(next);
        this.persist(next);
    }

    public reset(): void {
        this._settings.set({ ...DEFAULT_SETTINGS });
        this.persist(DEFAULT_SETTINGS);
    }

    private load(): ImportFlowSettings {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return { ...DEFAULT_SETTINGS };
            const parsed = JSON.parse(raw) as Partial<ImportFlowSettings>;
            return {
                preserveUuids:
                    typeof parsed.preserveUuids === 'boolean' ? parsed.preserveUuids : DEFAULT_SETTINGS.preserveUuids,
                replaceExisting:
                    typeof parsed.replaceExisting === 'boolean'
                        ? parsed.replaceExisting
                        : DEFAULT_SETTINGS.replaceExisting,
                importLabels:
                    typeof parsed.importLabels === 'boolean' ? parsed.importLabels : DEFAULT_SETTINGS.importLabels,
            };
        } catch {
            return { ...DEFAULT_SETTINGS };
        }
    }

    private persist(settings: ImportFlowSettings): void {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
        } catch {
            // ignore quota / disabled storage
        }
    }
}
