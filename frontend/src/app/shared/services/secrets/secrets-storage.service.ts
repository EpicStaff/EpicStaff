import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { BinnedSecret, CreateSecretRequest, Secret, SecretSelectItem } from '@shared/models';
import { catchError, finalize, forkJoin, map, Observable, of, shareReplay, tap, throwError } from 'rxjs';

import { StorageService } from '../app-storage.service';
import { SecretsApiService } from './secrets-api.service';

const TAIL_LENGTH = 4;

@Injectable({ providedIn: 'root' })
export class SecretsStorageService implements StorageService {
    private readonly secretsApiService = inject(SecretsApiService);

    private secretsSignal = signal<Secret[]>([]);
    public readonly secrets = this.secretsSignal.asReadonly();
    public secretsLoaded = signal<boolean>(false);
    private binnedSignal = signal<BinnedSecret[]>([]);
    /** Secrets in the recycle bin: a resource can still link to one until it's purged. */
    public readonly binnedSecrets = this.binnedSignal.asReadonly();
    // Every node-secrets-field and config dialog independently calls getSecrets() on their own
    // mount/build — without sharing the in-flight request, opening e.g. a CDT panel (pre + post
    // secrets fields mounting at once) fires one duplicate GET /secrets/ per concurrent caller
    // before the first response lands.
    private pendingRequest$: Observable<Secret[]> | null = null;

    getSecrets(forceRefresh = false): Observable<Secret[]> {
        if (this.secretsLoaded() && !forceRefresh) {
            return of(this.secretsSignal());
        }

        if (!this.pendingRequest$) {
            const live$ = this.secretsApiService.getSecrets().pipe(
                // A member/viewer has no access to this endpoint at all — that's a permanent,
                // by-design restriction (see SKIP_FORBIDDEN_RELOAD on this request), not a
                // failure worth surfacing as an error toast to every secrets consumer.
                // Cache it as "loaded, zero secrets" instead of rethrowing.
                catchError((err: HttpErrorResponse) => (err.status === 403 ? of([]) : throwError(() => err)))
            );
            // Only names a binned secret a picker still holds: a failure must never break the live list.
            const binned$ = this.secretsApiService.getBinnedSecrets().pipe(catchError(() => of([])));
            this.pendingRequest$ = forkJoin([live$, binned$]).pipe(
                tap(([, binned]) => this.binnedSignal.set(binned)),
                map(([secrets]) => secrets),
                tap((secrets) => this.createSecretsInCache(secrets)),
                finalize(() => (this.pendingRequest$ = null)),
                shareReplay({ bufferSize: 1, refCount: false })
            );
        }
        return this.pendingRequest$;
    }

    createSecret(dto: CreateSecretRequest): Observable<Secret> {
        return this.secretsApiService.createSecret(dto).pipe(tap((secret) => this.createOrUpdateSecretInCache(secret)));
    }

    deleteSecret(id: number): Observable<void> {
        return this.secretsApiService.deleteSecret(id).pipe(tap(() => this.moveSecretToBin(id)));
    }

    /**
     * A secret picker's options: the live secrets, plus each selected secret that's in the recycle
     * bin, so the field shows it instead of looking empty. A binned secret is never offered otherwise:
     * a new link to one is refused.
     */
    selectItems(selected: number | number[] | null | undefined): SecretSelectItem[] {
        const selectedIds = new Set(Array.isArray(selected) ? selected : selected == null ? [] : [selected]);
        const live = this.secretsSignal().map((secret) => ({
            name: secret.name,
            value: secret.id,
            tip: this.maskTail(secret.tail),
        }));
        const binned = this.binnedSignal()
            .filter((secret) => selectedIds.has(secret.id))
            .map((secret) => ({ name: `${secret.name} (in the recycle bin)`, value: secret.id }));
        return [...live, ...binned];
    }

    isBinned(id: number): boolean {
        return this.binnedSignal().some((secret) => secret.id === id);
    }

    /**
     * `value` is write-only and never returned by the API — the backend only ever
     * gives us `tail` (SecretEncryption.encrypt, django_app/tables/services/secrets/encryption.py:
     * last 4 chars, or "" if the original was under 9 chars). So the preview can only
     * ever be a fixed mask plus that tail, never real leading characters.
     */
    maskTail(tail: string): string {
        if (tail.length < TAIL_LENGTH) {
            return '••••••••';
        }
        return `••••${tail}`;
    }

    namesForIds(ids: number[]): string[] {
        const selected = new Set(ids);
        return this.secretsSignal()
            .filter((secret) => selected.has(secret.id))
            .map((secret) => secret.name);
    }

    private createOrUpdateSecretInCache(updated: Secret): void {
        this.secretsSignal.update((secrets) => {
            const index = secrets.findIndex((s) => s.id === updated.id);
            if (index >= 0) {
                secrets[index] = updated;
            } else {
                secrets.push(updated);
            }
            return [...secrets];
        });
    }

    private createSecretsInCache(secrets: Secret[]): void {
        this.secretsSignal.set(secrets);
        this.secretsLoaded.set(true);
    }

    /** A deleted secret goes to the recycle bin: pickers that still hold it name it as binned. */
    private moveSecretToBin(id: number): void {
        const deleted = this.secretsSignal().find((secret) => secret.id === id);
        this.secretsSignal.set(this.secretsSignal().filter((secret) => secret.id !== id));
        if (deleted) {
            this.binnedSignal.update((binned) => [...binned, { id: deleted.id, name: deleted.name }]);
        }
    }

    clear(): void {
        this.secretsSignal.set([]);
        this.binnedSignal.set([]);
        this.secretsLoaded.set(false);
    }
}
