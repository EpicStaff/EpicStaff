import { inject, Injectable } from '@angular/core';
import { NodeType } from '@shared/models';
import { Observable, Subject } from 'rxjs';

import { ScheduleTriggerNodeModel } from '../core/models/node.model';
import {
    ScheduleTriggerRuntimeState,
    withScheduleTriggerRuntimeState,
} from '../utils/save/schedule-trigger-runtime-state';
import { FlowService } from './flow.service';
import { SavedFlowStateService } from './saved-flow-state.service';

/** A schedule trigger's runtime state the backend changed by itself; see `ScheduleTriggerRuntimeService`. */
export interface ScheduleTriggerRuntimeUpdate {
    backendId: number;
    state: ScheduleTriggerRuntimeState;
}

/**
 * Brings what the backend changed on a schedule trigger by itself (a finished schedule turned off, its
 * next run, its run count) into the editor without it counting as the user's edit. The canvas node and
 * the dirty-tracking baseline are updated together here; the saved graph the save diff starts from
 * belongs to the flows page, which applies each `updates$` item to it with
 * `withGraphScheduleTriggerRuntimeState`. Otherwise the next save would send the schedule as changed,
 * which for a user without Flows:Run the save refuses.
 */
@Injectable({
    providedIn: 'root',
})
export class ScheduleTriggerRuntimeService {
    private readonly flowService = inject(FlowService);
    private readonly savedFlowState = inject(SavedFlowStateService);
    private readonly updatesSubject = new Subject<ScheduleTriggerRuntimeUpdate>();

    public readonly updates$: Observable<ScheduleTriggerRuntimeUpdate> = this.updatesSubject.asObservable();

    public apply(nodeId: string, state: ScheduleTriggerRuntimeState): void {
        const node = this.flowService
            .nodes()
            .find(
                (candidate): candidate is ScheduleTriggerNodeModel =>
                    candidate.id === nodeId && candidate.type === NodeType.SCHEDULE_TRIGGER
            );
        if (!node) return;
        this.flowService.updateNode(withScheduleTriggerRuntimeState(node, state));
        this.savedFlowState.updateNode(nodeId, (savedNode) =>
            savedNode.type === NodeType.SCHEDULE_TRIGGER ? withScheduleTriggerRuntimeState(savedNode, state) : savedNode
        );
        if (node.backendId != null) {
            this.updatesSubject.next({ backendId: node.backendId, state });
        }
    }
}
