import { inject, Injectable } from '@angular/core';

import { NodeType } from '../core/enums/node-type';
import { CdtExplanation } from '../core/models/classification-decision-table.model';
import { ClassificationDecisionTableNodeModel } from '../core/models/node.model';
import { CdtExplanationCacheService } from './cdt-explanation-cache.service';
import { FlowService } from './flow.service';

/**
 * Read and write for one table's explanations. The dialog holds one of these
 * instead of the canvas, so it stays unable to reach a node, a connection or a save.
 */
export interface CdtExplanationScope {
    get(stepKey: string): CdtExplanation | null;
    set(stepKey: string, value: CdtExplanation): void;
}

export interface CdtExplanationScopeOptions {
    /** The canvas node the explanations belong to. */
    readonly nodeId: string;
    /** Only for the `localStorage` key, which predates storing these on the node. */
    readonly backendId: number | null;
    /**
     * Every step the open dialog can display. Anything else on the node was filed
     * under a rule that no longer exists, and is dropped on the next write.
     */
    readonly liveStepKeys: ReadonlySet<string>;
}

/**
 * Where a generated explanation is kept: the node's `metadata.explanations`, saved
 * with the graph like any other node change.
 *
 * Writing here marks the canvas dirty on purpose — an explanation is worth keeping
 * for everyone who opens the flow. Two consequences are accepted: the save that
 * persists one saves the whole table, unsaved grid edits included, because bulk save
 * diffs by node; and one generated but never saved is gone on reload, which is what
 * the write-through to `CdtExplanationCacheService` covers.
 */
@Injectable({ providedIn: 'root' })
export class CdtExplanationStoreService {
    private readonly flowService = inject(FlowService);
    private readonly cache = inject(CdtExplanationCacheService);

    public forNode(options: CdtExplanationScopeOptions): CdtExplanationScope {
        const cacheKey = (stepKey: string): string => `${options.backendId ?? options.nodeId}|${stepKey}`;

        return {
            get: (stepKey) =>
                this.findNode(options.nodeId)?.explanations?.[stepKey] ?? this.cache.get(cacheKey(stepKey)),
            set: (stepKey, value) => {
                this.cache.set(cacheKey(stepKey), value);
                this.writeToNode(options, stepKey, value);
            },
        };
    }

    private writeToNode(options: CdtExplanationScopeOptions, stepKey: string, value: CdtExplanation): void {
        const node = this.findNode(options.nodeId);
        // Deleted from under the open dialog. The cache still has it.
        if (!node) return;

        // Keys filed under a rule that no longer exists are dropped here, the only
        // place it happens — the node's metadata rides along in every read of the graph.
        const explanations: Record<string, CdtExplanation> = { [stepKey]: value };
        for (const [key, existing] of Object.entries(node.explanations ?? {})) {
            if (key !== stepKey && options.liveStepKeys.has(key)) explanations[key] = existing;
        }

        // Nothing routing-related changed, so the connection reset has nothing to do.
        this.flowService.updateNode({ ...node, explanations }, { skipDecisionTableReset: true });
    }

    private findNode(nodeId: string): ClassificationDecisionTableNodeModel | null {
        const node = this.flowService.nodes().find((candidate) => candidate.id === nodeId);
        return node?.type === NodeType.CLASSIFICATION_TABLE ? node : null;
    }
}
