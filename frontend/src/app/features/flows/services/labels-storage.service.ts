import { computed, inject, Injectable, signal } from '@angular/core';
import { Observable, of } from 'rxjs';
import { catchError, shareReplay, tap } from 'rxjs/operators';

import { LabelColor, LabelDto, PatchLabelRequest } from '../models/label.model';
import { LabelsApiService } from './labels-api.service';

export interface LabelTreeNode extends LabelDto {
    children: LabelTreeNode[];
}

function buildTree(labels: LabelDto[]): LabelTreeNode[] {
    function getChildren(parentId: number | null): LabelTreeNode[] {
        return labels
            .filter((label) => label.parent === parentId)
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((label) => ({
                ...label,
                children: getChildren(label.id),
            }));
    }

    return getChildren(null);
}

@Injectable({ providedIn: 'root' })
export class LabelsStorageService {
    private readonly labelsApiService = inject(LabelsApiService);

    // --- State Signals ---
    private labelsSignal = signal<LabelDto[]>([]);
    private labelsLoaded = signal<boolean>(false);
    private activeLabelFilterSignal = signal<'all' | 'unlabeled' | number>('all');

    // --- Public State Accessors ---
    public readonly labels = this.labelsSignal.asReadonly();
    public readonly isLabelsLoaded = this.labelsLoaded.asReadonly();
    public readonly activeLabelFilter = this.activeLabelFilterSignal.asReadonly();

    public readonly labelTree = computed<LabelTreeNode[]>(() => buildTree(this.labelsSignal()));

    // --- Data Loading ---
    public loadLabels(forceRefresh = false): Observable<LabelDto[]> {
        if (this.labelsLoaded() && !forceRefresh) {
            return of(this.labelsSignal());
        }

        return this.labelsApiService.getLabels().pipe(
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

    // --- CRUD Methods ---
    public createLabel(name: string, parentId?: number | null, color?: LabelColor): Observable<LabelDto> {
        return this.labelsApiService
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

        return this.labelsApiService.patchLabel(id, patchData).pipe(
            tap((updatedLabel) => {
                const current = this.labelsSignal();
                this.labelsSignal.set(current.map((l) => (l.id === id ? updatedLabel : l)));
            })
        );
    }

    public updateLabelColor(id: number, color: LabelColor): Observable<LabelDto> {
        return this.labelsApiService.patchLabel(id, { metadata: { color } }).pipe(
            tap((updatedLabel) => {
                const current = this.labelsSignal();
                this.labelsSignal.set(current.map((l) => (l.id === id ? updatedLabel : l)));
            })
        );
    }

    public deleteLabel(id: number): Observable<void> {
        const label = this.labelsSignal().find((l) => l.id === id);
        const cascadePrefix = label ? label.full_path + '/' : null;

        return this.labelsApiService.deleteLabel(id).pipe(
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

    // --- Filter Setter ---
    public setActiveLabelFilter(filter: 'all' | 'unlabeled' | number): void {
        this.activeLabelFilterSignal.set(filter);
    }
}
