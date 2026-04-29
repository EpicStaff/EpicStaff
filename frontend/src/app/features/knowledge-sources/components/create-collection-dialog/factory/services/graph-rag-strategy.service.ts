import { Injectable } from '@angular/core';
import { Observable, of } from 'rxjs';
import { map, tap } from 'rxjs/operators';

import { CollectionGraphRag, CreateGraphRagIndexConfigRequest } from '../../../../models/graph-rag.model';
import { GraphRagService } from '../../../../services/graph-rag.service';
import { GraphRagConfigurationComponent } from '../../../graph-rag-configuration/graph-rag-configuration.component';
import { RagCreationStrategy } from '../interfaces/rag-creation-strategy.interface';

@Injectable({
    providedIn: 'root',
})
export class GraphRagStrategy implements RagCreationStrategy {
    private graphRag!: CollectionGraphRag;

    constructor(private graphRagService: GraphRagService) {}

    create(collectionId: number, embedderId: number, llmId: number): Observable<boolean> {
        return this.graphRagService.createRagForCollection(collectionId, embedderId, llmId).pipe(
            tap((res) => (this.graphRag = res.graph_rag)),
            map(() => true)
        );
    }

    startIndexing(dto: CreateGraphRagIndexConfigRequest): Observable<boolean> {
        const ragId = this.graphRag.graph_rag_id;
        if (!ragId || !dto) return of(false);

        return this.graphRagService
            .startIndexing({
                rag_id: ragId,
                rag_type: 'graph',
            })
            .pipe(map(() => true));
    }

    getConfigurationComponent() {
        return GraphRagConfigurationComponent;
    }

    getConfigurationInputs(): Record<string, unknown> {
        return { graphRag: this.graphRag };
    }
}
