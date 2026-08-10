import { computed, Injectable, signal } from '@angular/core';
import { buildLabelTree, LabelColor, LabelDto, LabelTreeNode, PatchLabelRequest } from '@shared/models';
import { Observable, of } from 'rxjs';
import { catchError, shareReplay, tap } from 'rxjs/operators';

import { LabelsApi, LabelsStore } from './labels-store.token';

// Local StorageService copy to avoid a circular import with app-storage.service.
interface StorageService {
    clear(): void;
}

/**
 * Reusable labels store. Feature-specific storage services extend this class
 * and only need to expose the HTTP api (matching {@link LabelsApi}). All state
 * management (signals, tree, cache, cascade delete) lives here so we don't
 * duplicate ~100 lines per feature.
 */
@Injectable()
export abstract class BaseLabelsStore implements LabelsStore, StorageService {
    protected abstract readonly api: LabelsApi;

    private labelsSignal = signal<LabelDto[]>([]);
    private labelsLoaded = signal<boolean>(false);
    private activeLabelFilterSignal = signal<'all' | 'unlabeled' | number>('all');

    public readonly labels = this.labelsSignal.asReadonly();
    public readonly isLabelsLoaded = this.labelsLoaded.asReadonly();
    public readonly activeLabelFilter = this.activeLabelFilterSignal.asReadonly();

    public readonly labelTree = computed<LabelTreeNode[]>(() => buildLabelTree(this.labelsSignal()));

    public loadLabels(forceRefresh = false): Observable<LabelDto[]> {
        if (this.labelsLoaded() && !forceRefresh) {
            return of(this.labelsSignal());
        }

        return this.api.getLabels().pipe(
            tap((labels) => {
                this.labelsSignal.set(labels);
                this.labelsLoaded.set(true);
            }),
            shareReplay(1),
            catchError(() => {
                this.labelsLoaded.set(false);
                return of([]);
            })
        );
    }

    public createLabel(name: string, parentId?: number | null, color?: LabelColor): Observable<LabelDto> {
        return this.api
            .createLabel({
                name,
                parent: parentId ?? null,
                metadata: { color: color ?? LabelColor.Default },
            })
            .pipe(
                tap((newLabel) => {
                    this.labelsSignal.set([...this.labelsSignal(), newLabel]);
                })
            );
    }

    public renameLabel(id: number, name: string, color?: LabelColor): Observable<LabelDto> {
        const label = this.labelsSignal().find((l) => l.id === id);
        if (!label) {
            throw new Error(`Label with id ${id} not found`);
        }

        const patchData: PatchLabelRequest = {
            metadata: { color: color ?? LabelColor.Default },
        };
        if (name !== label.name) {
            patchData.name = name;
        }

        return this.api.patchLabel(id, patchData).pipe(
            tap((updatedLabel) => {
                const current = this.labelsSignal();
                this.labelsSignal.set(current.map((l) => (l.id === id ? updatedLabel : l)));
            })
        );
    }

    public updateLabelColor(id: number, color: LabelColor): Observable<LabelDto> {
        return this.api.patchLabel(id, { metadata: { color } }).pipe(
            tap((updatedLabel) => {
                const current = this.labelsSignal();
                this.labelsSignal.set(current.map((l) => (l.id === id ? updatedLabel : l)));
            })
        );
    }

    public deleteLabel(id: number): Observable<void> {
        const label = this.labelsSignal().find((l) => l.id === id);
        const cascadePrefix = label ? label.full_path + '/' : null;

        return this.api.deleteLabel(id).pipe(
            tap(() => {
                const current = this.labelsSignal();
                const deletedIds = new Set<number>([id]);
                if (cascadePrefix) {
                    current.forEach((l) => {
                        if (l.full_path.startsWith(cascadePrefix)) {
                            deletedIds.add(l.id);
                        }
                    });
                }
                this.labelsSignal.set(current.filter((l) => !deletedIds.has(l.id)));
                const activeFilter = this.activeLabelFilterSignal();
                if (typeof activeFilter === 'number' && deletedIds.has(activeFilter)) {
                    this.activeLabelFilterSignal.set('all');
                }
            })
        );
    }

    public setActiveLabelFilter(filter: 'all' | 'unlabeled' | number): void {
        this.activeLabelFilterSignal.set(filter);
    }

    public clear(): void {
        this.labelsSignal.set([]);
        this.labelsLoaded.set(false);
        this.activeLabelFilterSignal.set('all');
    }
}
