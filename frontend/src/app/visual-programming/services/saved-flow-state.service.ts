import { computed, inject, Injectable, Signal, signal } from '@angular/core';

import { FlowModel } from '../core/models/flow.model';
import { NodeModel } from '../core/models/node.model';
import { toDirtyComparableFlowState } from '../utils/save';
import { FlowService } from './flow.service';

const EMPTY_FLOW: FlowModel = { nodes: [], connections: [] };

/**
 * The flow as last persisted to the backend: the baseline the editor page's dirty tracking
 * compares the canvas against. FlowService nodes can carry panel edits that were autosaved into
 * the canvas but never sent, so a panel that needs "what the backend holds" reads it from here.
 *
 * The editor page is the only writer, and it writes the root instance only. Scoped instances
 * (the version preview's, via FLOW_EDITOR_STATE_PROVIDERS) are never written, so every node in
 * them reports as never saved.
 */
@Injectable({
    providedIn: 'root',
})
export class SavedFlowStateService {
    private readonly savedFlowSignal = signal<FlowModel>(EMPTY_FLOW);
    private readonly flowService = inject(FlowService);
    public readonly savedFlow: Signal<FlowModel> = this.savedFlowSignal.asReadonly();

    /** Whether the canvas differs from the persisted flow; true after any edit, including undo of a saved deletion. */
    public readonly hasUnsavedChanges: Signal<boolean> = computed(() => {
        const current = toDirtyComparableFlowState(this.flowService.getFlowState());
        const saved = toDirtyComparableFlowState(this.savedFlowSignal());
        return JSON.stringify(current) !== JSON.stringify(saved);
    });

    public setSavedFlow(flow: FlowModel): void {
        this.savedFlowSignal.set(flow);
    }

    /** Puts `update(node)` in place of the saved node with this id; nothing when that node was never saved. */
    public updateNode(nodeId: string, update: (savedNode: NodeModel) => NodeModel): void {
        const flow = this.savedFlowSignal();
        if (!flow.nodes.some((node) => node.id === nodeId)) return;
        this.savedFlowSignal.set({
            ...flow,
            nodes: flow.nodes.map((node) => (node.id === nodeId ? update(node) : node)),
        });
    }

    public reset(): void {
        this.savedFlowSignal.set(EMPTY_FLOW);
    }

    /** The node as last saved, or null when it was never saved. Reactive when read inside a computed. */
    public savedNode(nodeId: string): NodeModel | null {
        return this.savedFlowSignal().nodes.find((node) => node.id === nodeId) ?? null;
    }
}
