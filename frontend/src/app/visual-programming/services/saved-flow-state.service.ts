import { Injectable, Signal, signal } from '@angular/core';

import { FlowModel } from '../core/models/flow.model';
import { NodeModel } from '../core/models/node.model';

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
    public readonly savedFlow: Signal<FlowModel> = this.savedFlowSignal.asReadonly();

    public setSavedFlow(flow: FlowModel): void {
        this.savedFlowSignal.set(flow);
    }

    public reset(): void {
        this.savedFlowSignal.set(EMPTY_FLOW);
    }

    /** The node as last saved, or null when it was never saved. Reactive when read inside a computed. */
    public savedNode(nodeId: string): NodeModel | null {
        return this.savedFlowSignal().nodes.find((node) => node.id === nodeId) ?? null;
    }
}
