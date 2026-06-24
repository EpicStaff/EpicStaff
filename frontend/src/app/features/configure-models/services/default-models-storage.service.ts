import { inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { Observable, of, tap } from 'rxjs';

import { GetDefaultModelsResponse, UpdateDefaultModelsRequest } from '../models/default-models.model';
import { DefaultModelsService } from './default-models.service';

@Injectable({ providedIn: 'root' })
export class DefaultModelsStorageService implements StorageService {
    private readonly defaultModelsApiService = inject(DefaultModelsService);

    private defaultModelsSignal = signal<GetDefaultModelsResponse | null>(null);
    private modelsLoaded = signal<boolean>(false);

    public readonly defaultModels = this.defaultModelsSignal.asReadonly();
    public readonly isDefaultModelsLoaded = this.modelsLoaded.asReadonly();

    loadDefaultModels(forceRefresh = false): Observable<GetDefaultModelsResponse | null> {
        if (this.isDefaultModelsLoaded() && !forceRefresh) {
            return of(this.defaultModelsSignal());
        }

        return this.defaultModelsApiService
            .getDefaultModels()
            .pipe(tap((models) => this.updateModelsInStorage(models)));
    }

    updateDefaultModels(data: UpdateDefaultModelsRequest): Observable<GetDefaultModelsResponse> {
        return this.defaultModelsApiService
            .updateDefaultModels(data)
            .pipe(tap((updated) => this.updateModelsInStorage(updated)));
    }

    updateModelsInStorage(updated: GetDefaultModelsResponse): void {
        this.defaultModelsSignal.set(updated);
        this.modelsLoaded.set(true);
    }

    markDefaultModelsOutdated(): void {
        this.modelsLoaded.set(false);
    }

    clear(): void {
        this.defaultModelsSignal.set(null);
        this.modelsLoaded.set(false);
    }
}
