import { Injectable } from '@angular/core';

import { RagType } from '../../../models/base-rag.model';
import { RagCreationStrategy } from './interfaces/rag-creation-strategy.interface';
import { GraphRagStrategy } from './services/graph-rag-strategy.service';
import { NaiveRagStrategy } from './services/naive-rag-strategy.service';

@Injectable({
    providedIn: 'root',
})
export class RagStrategyFactory {
    constructor(
        private naive: NaiveRagStrategy,
        private graph: GraphRagStrategy
    ) {}

    create(type: RagType): RagCreationStrategy {
        switch (type) {
            case 'naive':
                return this.naive;
            case 'graph':
                return this.graph;
            default:
                throw new Error('Unsupported RAG type');
        }
    }
}
