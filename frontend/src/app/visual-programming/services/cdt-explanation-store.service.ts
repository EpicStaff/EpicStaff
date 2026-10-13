import { inject, Injectable } from '@angular/core';
import { NodeType } from '@shared/models';

import {
    CdtExplanation,
    CdtExplanationKeyMove,
    CdtExplanations,
} from '../core/models/classification-decision-table.model';
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

/** The table whose explanations are read or written. */
export interface CdtExplanationNodeRef {
    /** The canvas node the explanations belong to. */
    readonly nodeId: string;
    /** Only for the `localStorage` key, which predates storing these on the node. */
    readonly backendId: number | null;
}

export interface CdtExplanationScopeOptions extends CdtExplanationNodeRef {
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
 * Every generated explanation also asks the page to persist that node's
 * explanations — only them, never the table edits they may have been generated
 * against — so closing the dialog cannot lose the text. The page debounces and
 * serialises those requests, which is why this can fire once per explanation. Each
 * explanation carries the fingerprint of the content it explained, so one
 * generated against edits that are later discarded shows as outdated against what
 * was saved. A `move` asks for no persist; see there.
 *
 * Until that persist lands the canvas reads as dirty; one that never lands leaves
 * it so (the next full save carries the explanations), and the write-through to
 * `CdtExplanationCacheService` keeps the text through a reload.
 *
 * A read-only editor (no Flows:Update, or a version preview) only reads: `set` and
 * `move` are no-ops there, so nothing reaches the node, the cache or a save. The
 * dialog hides its Explain actions in that case; this is the backstop. A preview also
 * skips the cache: that holds the live editor's text, and the preview shows only what
 * the version stored.
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
        return {
            get: (stepKey) =>
                this.findNode(options.nodeId)?.explanations?.[stepKey] ??
                (this.flowReadOnly.isPreview ? null : this.cache.get(this.cacheKey(options, stepKey))),
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

                this.cache.set(this.cacheKey(options, stepKey), value);
                // Deleted from under the open dialog: the cache still has it.
                if (node) {
                    this.writeToNode(node, stored);
                    // Every write, not only the last: the dialog cannot know which explanation
                    // is the final one, and a window closed mid-pass should keep what arrived.
                    this.sidePanelService.requestCdtExplanationsSave(node.id);
                }
                return true;
            },
        };
    }

    /**
     * Re-files a table's explanations under new step keys — a rule whose route code
     * or name was edited is filed under a new key (`explainKeyMovesForRuleEdit`), and
     * its text would otherwise stay behind under the old one. Each move takes the
     * entry under `from`, when there is one, and puts it under `to` over whatever is
     * there; a move with nothing under `from` changes nothing.
     *
     * Unlike `set`, it asks for no persist: the table edit that changed the keys is
     * still in the panel, and the panel's next save carries both. That defers, rather
     * than rules out, saved explanations filed under keys the saved rows do not have
     * yet: an explanation generated after the edit persists the moved keys through
     * `set`, and so does an explanations-only save still pending from an earlier one,
     * which reads the canvas node only when its turn in the queue comes — either can
     * land before the table does. The cache gets the new keys, so a reload before that
     * save still finds the text; the old ones stay there, which is what an undo back
     * over the edit falls back to.
     *
     * Refused, like `set`, when the stored map would have to drop an explanation it
     * keeps today to make room for a longer key.
     */
    public move(table: CdtExplanationNodeRef, moves: readonly CdtExplanationKeyMove[]): void {
        if (this.flowReadOnly.isReadOnly()) return;

        const node = this.findNode(table.nodeId);
        const before = node?.explanations ?? {};
        const moved = moves.filter(({ from }) => Object.hasOwn(before, from));
        if (!node || moved.length === 0) return;

        // Every `from` taken out before any `to` is written, each from the map as it
        // was: the order of the moves cannot matter, even where one move's `to` is
        // another's `from`.
        const after: Record<string, CdtExplanation> = { ...before };
        for (const { from } of moved) delete after[from];
        for (const { from, to } of moved) after[to] = before[from];

        const stored = toStoredCdtExplanations(after);
        const renamed = new Map(moved.map(({ from, to }) => [from, to]));
        const keepsEveryKept = Object.keys(toStoredCdtExplanations(before)).every((key) =>
            Object.hasOwn(stored, renamed.get(key) ?? key)
        );
        if (!keepsEveryKept) return;

        for (const { to } of moved) {
            if (Object.hasOwn(stored, to)) this.cache.set(this.cacheKey(table, to), stored[to]);
        }
        this.writeToNode(node, stored);
    }

    private writeToNode(node: ClassificationDecisionTableNodeModel, explanations: CdtExplanations): void {
        // Nothing routing-related changed, so the connection reset has nothing to do.
        // Sorted, as the save path stores them, so the persisted copy and the canvas
        // stringify identically and the node stops reading as dirty once it lands.
        const updated = { ...node, explanations };
        this.flowService.updateNode(updated, { skipDecisionTableReset: true });
    }

    private cacheKey(table: CdtExplanationNodeRef, stepKey: string): string {
        return `${table.backendId ?? table.nodeId}|${stepKey}`;
    }

    private findNode(nodeId: string): ClassificationDecisionTableNodeModel | null {
        const node = this.flowService.nodes().find((candidate) => candidate.id === nodeId);
        return node?.type === NodeType.CLASSIFICATION_TABLE ? node : null;
    }
}
