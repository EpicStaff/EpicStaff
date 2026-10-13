import { inject, Injectable } from '@angular/core';
import { NodeType } from '@shared/models';

import { CdtExplanation, CdtExplanations } from '../core/models/classification-decision-table.model';
import { ClassificationDecisionTableNodeModel } from '../core/models/node.model';
import { toStoredCdtExplanations } from '../utils/cdt-explanations';
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
    /**
     * False when the explanation is past the storage limits (`CDT_EXPLANATION_LIMITS`):
     * it is then kept nowhere — not on the node, not in the cache — so it never reads as saved.
     */
    set(stepKey: string, value: CdtExplanation): boolean;
}

export interface CdtExplanationScopeOptions {
    /** The canvas node the explanations belong to. */
    readonly nodeId: string;
    /** Only for the `localStorage` key, which predates storing these on the node. */
    readonly backendId: number | null;
    /**
     * Every key a step of this table can be filed under — the drawn steps and the
     * hidden rules alike (`buildRetainedExplainStepKeys`). Anything else on the node
     * was filed under a rule that no longer exists, and is dropped on the next write.
     */
    readonly retainedStepKeys: ReadonlySet<string>;
}

/**
 * Where a generated explanation is kept: the node's `metadata.explanations`.
 *
 * Every write also asks the page to persist that node's explanations — only them,
 * never the table edits they may have been generated against — so closing the
 * dialog cannot lose the text. The page debounces and serialises those requests,
 * which is why this can fire once per explanation. Each explanation carries the
 * fingerprint of the content it explained, so one generated against edits that
 * are later discarded shows as outdated against what was saved.
 *
 * Until that persist lands the canvas reads as dirty; one that never lands leaves
 * it so (the next full save carries the explanations), and the write-through to
 * `CdtExplanationCacheService` keeps the text through a reload.
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
                if (this.flowReadOnly.isReadOnly()) return true;

                const node = this.findNode(options.nodeId);
                // Keys filed under a rule that no longer exists are dropped here, the only
                // place it happens — the node's metadata rides along in every read of the graph.
                const others: Record<string, CdtExplanation> = {};
                for (const [key, existing] of Object.entries(node?.explanations ?? {})) {
                    if (key !== stepKey && options.retainedStepKeys.has(key)) others[key] = existing;
                }
                // Cut to what the backend stores, so its save never fails over one. Refused
                // when that cuts this one — or would push out one already kept to make room.
                const keptWithout = toStoredCdtExplanations(others);
                const stored = toStoredCdtExplanations({ ...others, [stepKey]: value });
                const fits =
                    Object.hasOwn(stored, stepKey) &&
                    Object.keys(keptWithout).every((key) => Object.hasOwn(stored, key));
                if (!fits) return false;

                this.cache.set(cacheKey(stepKey), value);
                // Deleted from under the open dialog: the cache still has it.
                if (node) this.writeToNode(node, stored);
                return true;
            },
        };
    }

    private writeToNode(node: ClassificationDecisionTableNodeModel, explanations: CdtExplanations): void {
        // Nothing routing-related changed, so the connection reset has nothing to do.
        // Sorted, as the save path stores them, so the persisted copy and the canvas
        // stringify identically and the node stops reading as dirty once it lands.
        const updated = { ...node, explanations };
        this.flowService.updateNode(updated, { skipDecisionTableReset: true });

        // Every write, not only the last: the dialog cannot know which explanation
        // is the final one, and a window closed mid-pass should keep what arrived.
        this.sidePanelService.requestCdtExplanationsSave(node.id);
    }

    private findNode(nodeId: string): ClassificationDecisionTableNodeModel | null {
        const node = this.flowService.nodes().find((candidate) => candidate.id === nodeId);
        return node?.type === NodeType.CLASSIFICATION_TABLE ? node : null;
    }
}
