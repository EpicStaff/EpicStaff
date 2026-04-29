import { inject, Injectable, signal } from '@angular/core';
import { LLMProvider, ModelTypes } from '@shared/models';
import { LLMProvidersService } from '@shared/services';
import { catchError, Observable, of, tap, throwError } from 'rxjs';

@Injectable({
    providedIn: 'root',
})
export class LlmProvidersStorageService {
    private readonly llmProvidersService = inject(LLMProvidersService);

    // All providers (unfiltered)
    private providersSignal = signal<LLMProvider[]>([]);
    private providersLoaded = signal<boolean>(false);

    public readonly providers = this.providersSignal.asReadonly();
    public readonly isProvidersLoaded = this.providersLoaded.asReadonly();

    // Per-type cache
    private providersByTypeSignal = signal<Map<ModelTypes, LLMProvider[]>>(new Map());
    private providerTypesLoaded = signal<Set<ModelTypes>>(new Set());

    public readonly providersByType = this.providersByTypeSignal.asReadonly();

    getProviders(forceRefresh = false): Observable<LLMProvider[]> {
        if (this.providersLoaded() && !forceRefresh) {
            return of(this.providersSignal());
        }
        return this.llmProvidersService.getProviders().pipe(
            tap((providers) => {
                this.providersSignal.set(providers);
                this.providersLoaded.set(true);
            }),
            catchError((err) => {
                this.providersLoaded.set(false);
                return throwError(() => err);
            })
        );
    }

    getProvidersByType(type: ModelTypes, forceRefresh = false): Observable<LLMProvider[]> {
        const loadedTypes = this.providerTypesLoaded();
        if (loadedTypes.has(type) && !forceRefresh) {
            return of(this.providersByTypeSignal().get(type) ?? []);
        }
        return this.llmProvidersService.getProvidersByQuery(type).pipe(
            tap((providers) => {
                this.providersByTypeSignal.update((map) => {
                    const updated = new Map(map);
                    updated.set(type, providers);
                    return updated;
                });
                this.providerTypesLoaded.update((set) => {
                    const updated = new Set(set);
                    updated.add(type);
                    return updated;
                });
            }),
            catchError((err) => {
                this.providerTypesLoaded.update((set) => {
                    const updated = new Set(set);
                    updated.delete(type);
                    return updated;
                });
                return throwError(() => err);
            })
        );
    }
}
