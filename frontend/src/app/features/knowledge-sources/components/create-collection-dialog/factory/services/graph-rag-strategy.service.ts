import { Injectable, Signal, signal } from '@angular/core';
import { Observable, of } from 'rxjs';
import { map, tap } from 'rxjs/operators';

import { ToastService } from '../../../../../../services/notifications';
import { CollectionGraphRag, CreateGraphRagIndexConfigRequest } from '../../../../models/graph-rag.model';
import { GraphRagService } from '../../../../services/graph-rag.service';
import { RagIndexingService } from '../../../../services/rag-indexing.service';
import { GraphRagConfigurationComponent } from '../../../graph-rag-configuration/graph-rag-configuration.component';
import { RagCreationStrategy } from '../interfaces/rag-creation-strategy.interface';

@Injectable({
    providedIn: 'root',
})
export class GraphRagStrategy implements RagCreationStrategy {
    private graphRag!: CollectionGraphRag;
    readonly canIndex: Signal<boolean> = signal(true);

    constructor(
        private graphRagService: GraphRagService,
        private ragIndexingService: RagIndexingService,
        private toastService: ToastService
    ) {}

    create(collectionId: number, embedderId: number, llmId: number): Observable<boolean> {
        return this.graphRagService.createRagForCollection(collectionId, embedderId, llmId).pipe(
            tap((res) => (this.graphRag = res.graph_rag)),
            map(() => true)
        );
    }

    startIndexing(dto: CreateGraphRagIndexConfigRequest): Observable<boolean> {
        const ragId = this.graphRag.graph_rag_id;
        if (!ragId || !dto) return of(false);

        return this.ragIndexingService
            .startIndexing({
                rag_id: ragId,
                rag_type: 'graph',
            })
            .pipe(
                tap(() => this.toastService.success('Indexing started')),
                map(() => true)
            );
    }

    stopIndexing() {
        const ragId = this.graphRag.graph_rag_id;
        if (!ragId) return of(false);

        return this.ragIndexingService
            .stopIndexing({
                rag_id: ragId,
                rag_type: 'graph',
            })
            .pipe(
                tap(() => this.toastService.success('Indexing stop triggered')),
                map(() => true)
            );
    }

    getConfigurationComponent() {
        return GraphRagConfigurationComponent;
    }

    getConfigurationInputs(): Record<string, unknown> {
        return { graphRag: this.graphRag };
    }
}
