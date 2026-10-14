import { Signal, Type } from '@angular/core';
import { Observable } from 'rxjs';

import { IndexingEstimate } from '../../../../models/base-rag.model';

export interface RagCreationStrategy {
    canIndex: Signal<boolean>;
    isIndexing: Signal<boolean>;
    create(collectionId: number, embedderId: number, llmId?: number): Observable<boolean>;
    startIndexing(data?: unknown): Observable<boolean>;
    estimateIndexing(configIds: number[], indexConfig?: unknown): Observable<IndexingEstimate | null>;
    stopIndexing(): Observable<boolean>;
    getConfigurationComponent(): Type<unknown>;
    getConfigurationInputs(): Record<string, unknown>;
    dispose?(): void;
}
