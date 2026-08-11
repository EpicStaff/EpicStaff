import { inject, Injectable } from '@angular/core';
import { SecretUsageCategoryDto, SecretUsageFlowItemDto, SecretUsageNamedItemDto } from '@shared/models';
import { forkJoin, map, Observable, of, shareReplay, switchMap } from 'rxjs';

import { SecretsApiService } from './secrets-api.service';
import { SecretsStorageService } from './secrets-storage.service';

@Injectable({ providedIn: 'root' })
export class SecretDeclarationIndexService {
    private readonly secretsApiService = inject(SecretsApiService);
    private readonly secretsStorageService = inject(SecretsStorageService);

    private index$: Observable<Map<string, number[]>> | null = null;

    getIndex(): Observable<Map<string, number[]>> {
        if (!this.index$) {
            this.index$ = this.buildIndex().pipe(shareReplay({ bufferSize: 1, refCount: false }));
        }
        return this.index$;
    }

    invalidate(): void {
        this.index$ = null;
    }

    lookup(
        index: Map<string, number[]>,
        graphId: number,
        nodeName: string,
        nodeType: string,
        codeField: string
    ): number[] {
        return index.get(this.key(graphId, nodeName, nodeType, codeField)) ?? [];
    }

    lookupTool(index: Map<string, number[]>, toolName: string): number[] {
        return index.get(this.toolKey(toolName)) ?? [];
    }

    private key(graphId: number, nodeName: string, nodeType: string, codeField: string | null): string {
        return `${graphId}:${nodeName}:${nodeType}:${codeField ?? ''}`;
    }

    private toolKey(toolName: string): string {
        return `tool:${toolName}`;
    }

    private addToIndex(index: Map<string, number[]>, key: string, secretId: number): void {
        const ids = index.get(key);
        if (ids) {
            ids.push(secretId);
        } else {
            index.set(key, [secretId]);
        }
    }

    private buildIndex(): Observable<Map<string, number[]>> {
        return this.secretsStorageService.getSecrets().pipe(
            switchMap((secrets) =>
                secrets.length
                    ? forkJoin(
                          secrets.map((secret) =>
                              this.secretsApiService
                                  .getSecretUsage(secret.id)
                                  .pipe(map((usage) => ({ secretId: secret.id, categories: usage.categories })))
                          )
                      )
                    : of([])
            ),
            map((results) => {
                const index = new Map<string, number[]>();
                for (const { secretId, categories } of results) {
                    for (const category of categories as SecretUsageCategoryDto[]) {
                        if (category.key === 'flows') {
                            for (const flow of category.items as SecretUsageFlowItemDto[]) {
                                for (const node of flow.nodes) {
                                    const key = this.key(flow.id, node.name, node.node_type, node.code_field);
                                    this.addToIndex(index, key, secretId);
                                }
                            }
                        } else if (category.key === 'tools') {
                            for (const item of category.items as SecretUsageNamedItemDto[]) {
                                this.addToIndex(index, this.toolKey(item.name), secretId);
                            }
                        }
                    }
                }
                return index;
            })
        );
    }
}
