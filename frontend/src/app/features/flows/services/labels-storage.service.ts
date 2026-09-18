import { inject, Injectable } from '@angular/core';

import { BaseLabelsStore } from '../../../shared/services/base-labels-store.service';
import { LabelsApiService } from './labels-api.service';

// Re-export so historical imports of LabelTreeNode from this file keep working.
export type { LabelTreeNode } from '@shared/models';

/**
 * Flows-scoped labels store. All state/logic lives in BaseLabelsStore; this
 * subclass only wires the flows-specific HTTP API. Provided at root so root
 * consumers (FlowsStorageService, AppStorageService) can inject it.
 */
@Injectable({ providedIn: 'root' })
export class LabelsStorageService extends BaseLabelsStore {
    protected readonly api = inject(LabelsApiService);
}
