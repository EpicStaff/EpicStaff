import { inject, Injectable } from '@angular/core';
import { NodeType } from '@shared/models';

import { CdtExplanation } from '../core/models/classification-decision-table.model';
import { ClassificationDecisionTableNodeModel } from '../core/models/node.model';
import { CdtExplanationCacheService } from './cdt-explanation-cache.service';
import { FlowService } from './flow.service';
import { FlowReadOnlyService } from './flow-readonly.service';
import { SidePanelService } from './side-panel.service';

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
 * Every write also asks the page to save that node, so closing the dialog cannot
 * lose the text. The page debounces and serialises those requests, which is why
 * this can fire once per explanation.
 *
 * The save carries the whole table, unsaved grid edits included, because bulk save
 * diffs by node. A save that never lands leaves the canvas dirty, and the
 * write-through to `CdtExplanationCacheService` keeps the text through a reload.
 *
 * A read-only editor (no Flows:Update, or a version preview) only reads: `set` is a
 * no-op there, so nothing reaches the node, the cache or a save. The dialog hides its
 * Explain actions in that case; this is the backstop. A preview also skips the cache:
 * that holds the live editor's text, and the preview shows only what the version stored.
 *
 * Listed in FLOW_EDITOR_STATE_PROVIDERS because it reads the editor through FlowService.
 */
@Injectable({ providedIn: 'root' })
export class CdtExplanationStoreService {
    private readonly flowService = inject(FlowService);
    private readonly sidePanelService = inject(SidePanelService);
    private readonly flowReadOnly = inject(FlowReadOnlyService);
    private readonly cache = inject(CdtExplanationCacheService);

    public forNode(options: CdtExplanationScopeOptions): CdtExplanationScope {
        const cacheKey = (stepKey: string): string => `${options.backendId ?? options.nodeId}|${stepKey}`;

        return {
            get: (stepKey) =>
                this.findNode(options.nodeId)?.explanations?.[stepKey] ??
                (this.flowReadOnly.isPreview ? null : this.cache.get(cacheKey(stepKey))),
            set: (stepKey, value) => {
                if (this.flowReadOnly.isReadOnly()) return;
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
        const updated = { ...node, explanations };
        this.flowService.updateNode(updated, { skipDecisionTableReset: true });

        // Every write, not only the last: the dialog cannot know which explanation
        // is the final one, and a window closed mid-pass should keep what arrived.
        this.sidePanelService.requestNodeAutosave(updated);
    }

    private findNode(nodeId: string): ClassificationDecisionTableNodeModel | null {
        const node = this.flowService.nodes().find((candidate) => candidate.id === nodeId);
        return node?.type === NodeType.CLASSIFICATION_TABLE ? node : null;
    }
}
