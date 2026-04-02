import { inject, Injectable, signal } from '@angular/core';
import { catchError, Observable, of, throwError } from 'rxjs';
import { tap } from 'rxjs/operators';

import { CreateNgrokConfigRequest, GetNgrokConfigResponse } from '../../models/ngrok-config.model';
import { NgrokConfigApiService } from './ngrok-config-api.service';

@Injectable({
    providedIn: 'root',
})
export class NgrokConfigStorageService {
    private configsSignal = signal<GetNgrokConfigResponse[]>([]);
    public readonly configs = this.configsSignal.asReadonly();
    public configsLoaded = signal<boolean>(false);

    private readonly ngrokConfigApiService = inject(NgrokConfigApiService);

    createConfig(dto: CreateNgrokConfigRequest): Observable<GetNgrokConfigResponse> {
        return this.ngrokConfigApiService.createNgrokConfig(dto).pipe(
            tap((config: GetNgrokConfigResponse) => this.createOrUpdateConfigInCache(config)),
            catchError((err) => throwError(() => err))
        );
    }

    getConfigs(): Observable<GetNgrokConfigResponse[]> {
        if (this.configsLoaded()) {
            return of(this.configsSignal());
        }

        return this.ngrokConfigApiService.getNgrokConfigs().pipe(
            tap((configs: GetNgrokConfigResponse[]) => this.createConfigsInCache(configs)),
            catchError((err) => {
                this.configsLoaded.set(false);
                return throwError(() => err);
            })
        );
    }

    getConfigById(id: number): Observable<GetNgrokConfigResponse> {
        return this.ngrokConfigApiService.getNgrokConfigById(id).pipe(
            tap((config: GetNgrokConfigResponse) => this.createOrUpdateConfigInCache(config)),
            catchError((err) => throwError(() => err))
        );
    }

    updateConfigById(id: number, config: Partial<CreateNgrokConfigRequest>): Observable<GetNgrokConfigResponse> {
        return this.ngrokConfigApiService.updateNgrokConfig(id, config).pipe(
            tap((config: GetNgrokConfigResponse) => this.createOrUpdateConfigInCache(config)),
            catchError((err) => throwError(() => err))
        );
    }

    deleteConfigById(id: number): Observable<void> {
        return this.ngrokConfigApiService.deleteNgrokConfig(id).pipe(
            tap(() => this.deleteConfigFromCache(id)),
            catchError((err) => throwError(() => err))
        );
    }

    private createOrUpdateConfigInCache(updated: GetNgrokConfigResponse): void {
        this.configsSignal.update((configs) => {
            const index = configs.findIndex((c) => c.id === updated.id);

            if (index >= 0) {
                configs[index] = updated;
            } else {
                configs.push(updated);
            }
            return [...configs];
        });
    }

    private createConfigsInCache(configs: GetNgrokConfigResponse[]): void {
        this.configsSignal.set(configs);
        this.configsLoaded.set(true);
    }

    private deleteConfigFromCache(id: number): void {
        const current = this.configsSignal();
        const updated = current.filter((c) => c.id !== id);

        this.configsSignal.set(updated);
    }
}
