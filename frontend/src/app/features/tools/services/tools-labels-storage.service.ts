import { inject, Injectable } from '@angular/core';

import { BaseLabelsStore } from '../../../shared/services/base-labels-store.service';
import { ToolsLabelsService } from './tools-labels.service';

/**
 * Tools-scoped labels store. All state/logic lives in BaseLabelsStore; this
 * subclass only wires the tools-specific HTTP API.
 */
@Injectable({ providedIn: 'root' })
export class ToolsLabelsStorageService extends BaseLabelsStore {
    protected readonly api = inject(ToolsLabelsService);
}
