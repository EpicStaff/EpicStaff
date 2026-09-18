import { InjectionToken, Signal } from '@angular/core';
import { CreateLabelRequest, LabelColor, LabelDto, LabelTreeNode, PatchLabelRequest } from '@shared/models';
import { Observable } from 'rxjs';

/**
 * Feature-agnostic HTTP contract for label CRUD. Each feature exposes its own
 * concrete class (backed by its own endpoint) that satisfies this shape and
 * hands it to BaseLabelsStore. Adding a new consumer only requires writing
 * these four methods against its endpoint.
 */
export interface LabelsApi {
    getLabels(): Observable<LabelDto[]>;
    createLabel(data: CreateLabelRequest): Observable<LabelDto>;
    patchLabel(id: number, data: PatchLabelRequest): Observable<LabelDto>;
    deleteLabel(id: number): Observable<void>;
}

/**
 * Contract for a store that backs the shared LabelSidebarComponent.
 * Each feature (flows, tools, ...) provides its own implementation via
 * the LABELS_STORE token so the sidebar stays feature-agnostic.
 */
export interface LabelsStore {
    readonly labels: Signal<LabelDto[]>;
    readonly labelTree: Signal<LabelTreeNode[]>;
    readonly activeLabelFilter: Signal<'all' | 'unlabeled' | number>;

    loadLabels(forceRefresh?: boolean): Observable<LabelDto[]>;
    createLabel(name: string, parentId?: number | null, color?: LabelColor): Observable<LabelDto>;
    renameLabel(id: number, name: string, color?: LabelColor): Observable<LabelDto>;
    deleteLabel(id: number): Observable<void>;
    setActiveLabelFilter(filter: 'all' | 'unlabeled' | number): void;
}

export const LABELS_STORE = new InjectionToken<LabelsStore>('LABELS_STORE');
