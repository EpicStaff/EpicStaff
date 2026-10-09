import { DestroyRef, inject, Injectable, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Observable, ReplaySubject, tap } from 'rxjs';

import { ImportResult } from '../../../core/models/import-result.model';
import { AuditPreset, AuditPresetBody, AuditPresetChanges, AuditPresetScope } from '../models/audit-preset.models';
import { AuditPresetsApiService } from './audit-presets-api.service';

// Provided by the filters panel: one list per panel open, shared by both preset tabs and their counts.
// Requests live as long as the panel, so switching tabs never drops a response.
@Injectable()
export class AuditPresetsStorageService {
    private readonly presetsSignal = signal<AuditPreset[]>([]);
    private readonly isLoadingSignal = signal(true);
    private readonly loadErrorSignal = signal(false);

    public readonly presets = this.presetsSignal.asReadonly();
    public readonly isLoading = this.isLoadingSignal.asReadonly();
    public readonly loadError = this.loadErrorSignal.asReadonly();

    private readonly presetsApi = inject(AuditPresetsApiService);
    private readonly destroyRef = inject(DestroyRef);

    public load(): void {
        this.loadErrorSignal.set(false);
        this.presetsApi
            .getPresets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (presets) => {
                    this.presetsSignal.set(presets);
                    this.isLoadingSignal.set(false);
                },
                error: () => {
                    this.loadErrorSignal.set(true);
                    this.isLoadingSignal.set(false);
                },
            });
    }

    // "Mine" holds only my private presets; "Shared" holds every shared preset, mine and colleagues'.
    public presetsInScope(scope: AuditPresetScope): AuditPreset[] {
        return this.presets().filter((preset) =>
            scope === 'shared' ? preset.is_shared : preset.is_owner && !preset.is_shared
        );
    }

    public createPreset(name: string, filterBody: AuditPresetBody, isShared: boolean): Observable<AuditPreset> {
        return this.run(this.presetsApi.createPreset(name, filterBody, isShared), (created) =>
            this.presetsSignal.update((presets) => [created, ...presets])
        );
    }

    public updatePreset(id: number, changes: AuditPresetChanges): Observable<AuditPreset> {
        return this.run(this.presetsApi.updatePreset(id, changes), (saved) =>
            this.presetsSignal.update((presets) => presets.map((preset) => (preset.id === saved.id ? saved : preset)))
        );
    }

    public duplicatePreset(id: number, isShared = false): Observable<AuditPreset> {
        return this.run(this.presetsApi.duplicatePreset(id, isShared), (copy) =>
            this.presetsSignal.update((presets) => {
                const index = presets.findIndex((preset) => preset.id === id);
                return [...presets.slice(0, index + 1), copy, ...presets.slice(index + 1)];
            })
        );
    }

    public deletePreset(id: number): Observable<void> {
        return this.run(this.presetsApi.deletePreset(id), () =>
            this.presetsSignal.update((presets) => presets.filter((preset) => preset.id !== id))
        );
    }

    // Imported presets get server-made names and ids, so the list is reloaded rather than patched.
    public importPresets(file: File): Observable<ImportResult> {
        return this.run(this.presetsApi.importPresets(file), () => this.load());
    }

    // Subscribes here, tied to the panel, and replays the outcome so a caller may listen with a shorter lifetime.
    private run<T>(request: Observable<T>, applyToList: (value: T) => void): Observable<T> {
        const outcome = new ReplaySubject<T>(1);
        request.pipe(tap(applyToList), takeUntilDestroyed(this.destroyRef)).subscribe(outcome);
        return outcome;
    }
}
