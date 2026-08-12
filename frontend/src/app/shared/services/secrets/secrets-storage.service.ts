import { inject, Injectable, signal } from '@angular/core';
import { CreateSecretRequest, Secret } from '@shared/models';
import { finalize, Observable, of, shareReplay, tap } from 'rxjs';

import { SecretsApiService } from './secrets-api.service';

const TAIL_LENGTH = 4;

@Injectable({ providedIn: 'root' })
export class SecretsStorageService {
    private readonly secretsApiService = inject(SecretsApiService);

    private secretsSignal = signal<Secret[]>([]);
    public readonly secrets = this.secretsSignal.asReadonly();
    public secretsLoaded = signal<boolean>(false);
    // Every node-secrets-field, config dialog, and SecretDeclarationIndexService independently
    // calls getSecrets() on their own mount/build — without sharing the in-flight request, opening
    // e.g. a CDT panel (pre + post secrets fields mounting at once) fires one duplicate GET
    // /secrets/ per concurrent caller before the first response lands.
    private pendingRequest$: Observable<Secret[]> | null = null;

    getSecrets(forceRefresh = false): Observable<Secret[]> {
        if (this.secretsLoaded() && !forceRefresh) {
            return of(this.secretsSignal());
        }

        if (!this.pendingRequest$) {
            this.pendingRequest$ = this.secretsApiService.getSecrets().pipe(
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
        return this.secretsApiService.deleteSecret(id).pipe(tap(() => this.deleteSecretFromCache(id)));
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

    private deleteSecretFromCache(id: number): void {
        const current = this.secretsSignal();
        const updated = current.filter((s) => s.id !== id);
        this.secretsSignal.set(updated);
    }

    clear(): void {
        this.secretsSignal.set([]);
        this.secretsLoaded.set(false);
    }
}
