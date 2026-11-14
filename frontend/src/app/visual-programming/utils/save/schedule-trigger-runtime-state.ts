import { GraphDto } from '../../../features/flows/models/graph.model';
import { ScheduleTriggerNodeModel } from '../../core/models/node.model';
import { GetScheduleTriggerNodeRequest } from '../../core/models/schedule-trigger.model';

/**
 * What the backend changes on a schedule trigger by itself, without anyone editing the node: it turns
 * a finished schedule off, moves its next run and counts its runs. Read from the schedule trigger
 * endpoint while the node's panel is open.
 */
export interface ScheduleTriggerRuntimeState {
    /** Left out to keep the active flag as it is. */
    isActive?: boolean;
    nextRunDateTime: string | null;
    currentRuns: number;
}

export function toScheduleTriggerRuntimeState(
    dto: GetScheduleTriggerNodeRequest,
    { includeIsActive }: { includeIsActive: boolean }
): ScheduleTriggerRuntimeState {
    return {
        ...(includeIsActive ? { isActive: dto.is_active } : {}),
        nextRunDateTime: dto.schedule?.next_run_date_time ?? null,
        currentRuns: dto.current_runs,
    };
}

export function withScheduleTriggerRuntimeState(
    node: ScheduleTriggerNodeModel,
    state: ScheduleTriggerRuntimeState
): ScheduleTriggerNodeModel {
    return {
        ...node,
        data: {
            ...node.data,
            isActive: state.isActive ?? node.data.isActive,
            nextRunDateTime: state.nextRunDateTime,
            currentRuns: state.currentRuns,
        },
    };
}

/** The saved graph with the runtime state of schedule trigger `backendId` applied, as the backend now has it. */
export function withGraphScheduleTriggerRuntimeState(
    graph: GraphDto,
    backendId: number,
    state: ScheduleTriggerRuntimeState
): GraphDto {
    return {
        ...graph,
        schedule_trigger_node_list: graph.schedule_trigger_node_list.map((row) =>
            row.id !== backendId
                ? row
                : {
                      ...row,
                      is_active: state.isActive ?? row.is_active,
                      current_runs: state.currentRuns,
                      schedule: row.schedule && { ...row.schedule, next_run_date_time: state.nextRunDateTime },
                  }
        ),
    };
}
