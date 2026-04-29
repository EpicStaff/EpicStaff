import { Type } from '@angular/core';
import { Observable } from 'rxjs';

export interface RagCreationStrategy {
    create(collectionId: number, embedderId: number, llmId?: number): Observable<boolean>;
    startIndexing(data?: unknown): Observable<boolean>;
    getConfigurationComponent(): Type<unknown>;
    getConfigurationInputs(): Record<string, unknown>;
}
