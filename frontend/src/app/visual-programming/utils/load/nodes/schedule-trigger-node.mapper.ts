import { stableNodeId } from '../../stable-node-id';

import {
    GetScheduleTriggerNodeRequest,
    ScheduleEndType,
    ScheduleIntervalUnit,
    ScheduleRunMode,
    ScheduleTriggerNodeData,
    WeekdayCode,
} from '../../../../pages/flows-page/components/flow-visual-programming/models/schedule-trigger.model';
import { NodeType } from '../../../core/enums/node-type';
import { ScheduleTriggerNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

function normalizeTimezone(iana: string | null | undefined): string {
    const raw = iana ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
    return raw === 'Europe/Kiev' ? 'Europe/Kyiv' : raw;
}

/**
 * Rewrites legacy "Once on DD MMM YYYY at HH:MM" names to the new
 * "Once on DD MMM YYYY at HH-MM" format (colon → hyphen in the time part).
 * Returns the input unchanged if it does not match the legacy pattern.
 * Names that already use a hyphen or carry a " #N" suffix are left untouched.
 */
export function rewriteLegacyOnceScheduleName(name: string): string {
    return name.replace(
        /^(Once on \d{2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4} at )(\d{2}):(\d{2})((?:\s#\d+)?)$/,
        '$1$2-$3$4'
    );
}

export function mapScheduleTriggerNodeToModel(dto: GetScheduleTriggerNodeRequest): ScheduleTriggerNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(dto.metadata, NodeType.SCHEDULE_TRIGGER);

    // schedule may be null for draft nodes that were saved before a schedule was configured.
    const schedule = dto.schedule ?? null;

    const runMode: ScheduleRunMode = schedule?.run_mode ?? 'once';
    const interval = schedule?.interval ?? null;

    const intervalEvery: number | null = interval?.every ?? null;
    const intervalUnit: ScheduleIntervalUnit | null = (interval?.unit as ScheduleIntervalUnit) ?? null;
    const weekdays: WeekdayCode[] = (interval?.weekdays as WeekdayCode[]) ?? [];

    const endType: ScheduleEndType = (schedule?.end?.type as ScheduleEndType) ?? 'never';
    const endDateTime: string | null = endType === 'on_date' ? (schedule?.end?.date_time ?? null) : null;
    const maxRuns: number | null = endType === 'after_n_runs' ? (schedule?.end?.max_runs ?? null) : null;

    const data: ScheduleTriggerNodeData = {
        isActive: dto.is_active,
        runMode,
        startDateTime: schedule?.start_date_time ?? '',
        intervalEvery,
        intervalUnit,
        weekdays,
        endType,
        endDateTime,
        maxRuns,
        currentRuns: dto.current_runs ?? 0,
        timezone: normalizeTimezone(schedule?.timezone),
        nextRunDateTime: schedule?.next_run_date_time ?? null,
    };

    return {
        id: stableNodeId(NodeType.SCHEDULE_TRIGGER, dto.id),
        backendId: dto.id,
        type: NodeType.SCHEDULE_TRIGGER,
        node_name: dto.node_name,
        nodeNumber: ui.nodeNumber,
        data,
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: {},
        output_variable_path: null,
        size: ui.size,
    };
}
