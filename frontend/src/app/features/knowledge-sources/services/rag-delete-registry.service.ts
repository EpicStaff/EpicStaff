import { inject, Injectable } from '@angular/core';
import { Observable, of } from 'rxjs';

import { RagType } from '../models/base-rag.model';
import { NaiveRagService } from './naive-rag.service';

export interface RagDeleteHandler {
    deleteRag(ragId: number): Observable<unknown>;
}

@Injectable({
    providedIn: 'root',
})
export class RagDeleteRegistryService {
    private naiveRagService = inject(NaiveRagService);

    private handlers: Partial<Record<RagType, RagDeleteHandler>> = {
        naive: { deleteRag: (ragId) => this.naiveRagService.deleteNaiveRag(ragId) },
        graph: { deleteRag: (ragId) => of(ragId) },
    };

    deleteRag(type: RagType, ragId: number): Observable<unknown> {
        const handler = this.handlers[type];
        if (!handler) {
            throw new Error(`No delete handler registered for RAG type: ${type}`);
        }
        return handler.deleteRag(ragId);
    }
}
