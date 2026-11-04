import { DestroyRef, inject, Injectable, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Observable, ReplaySubject, tap } from 'rxjs';

import { ToolFilterPreset, ToolFilterPresetUpdate } from '../models/tool-filter-preset.model';
import { ToolFilterPresetsApiService } from './tool-filter-presets-api.service';

/**
 * Component-scoped cache for tool filter presets — one instance per sidebar open,
 * destroyed with the sidebar. Not registered with APP_STORAGE because the
 * component-level lifecycle already handles cleanup; a root-level registration
 * would create a separate, never-destroyed singleton.
 */
@Injectable()
export class ToolFilterPresetsStorageService {
    private readonly presetsSignal = signal<ToolFilterPreset[]>([]);
    private readonly isLoadingSignal = signal(true);
    private readonly loadErrorSignal = signal(false);

    public readonly presets = this.presetsSignal.asReadonly();
    public readonly isLoading = this.isLoadingSignal.asReadonly();
    public readonly loadError = this.loadErrorSignal.asReadonly();

    private readonly presetsApi = inject(ToolFilterPresetsApiService);
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

    public createPreset(name: string, filterBody: Record<string, unknown>): Observable<ToolFilterPreset> {
        return this.run(this.presetsApi.createPreset({ name, filter_body: filterBody }), (created) =>
            this.presetsSignal.update((presets) => [created, ...presets])
        );
    }

    public updatePreset(id: number, changes: ToolFilterPresetUpdate): Observable<ToolFilterPreset> {
        return this.run(this.presetsApi.updatePreset(id, changes), (saved) =>
            this.presetsSignal.update((presets) => presets.map((preset) => (preset.id === saved.id ? saved : preset)))
        );
    }

    public deletePreset(id: number): Observable<void> {
        return this.run(this.presetsApi.deletePreset(id), () =>
            this.presetsSignal.update((presets) => presets.filter((preset) => preset.id !== id))
        );
    }

    public clear(): void {
        this.presetsSignal.set([]);
        this.isLoadingSignal.set(true);
        this.loadErrorSignal.set(false);
    }

    private run<T>(request: Observable<T>, applyToList: (value: T) => void): Observable<T> {
        const outcome = new ReplaySubject<T>(1);
        request.pipe(tap(applyToList), takeUntilDestroyed(this.destroyRef)).subscribe(outcome);
        return outcome;
    }
}
