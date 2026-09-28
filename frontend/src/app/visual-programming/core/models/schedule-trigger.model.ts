export type WeekdayCode = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun';

export type ScheduleRunMode = 'once' | 'repeat';

export type ScheduleIntervalUnit = 'seconds' | 'minutes' | 'hours' | 'days' | 'weeks' | 'months';

export type ScheduleEndType = 'never' | 'on_date' | 'after_n_runs';

// ── Request-side types (fully configured schedule, all fields non-null) ──────

export interface ScheduleIntervalBlock {
    every: number;
    unit: ScheduleIntervalUnit;
    weekdays: WeekdayCode[];
}

export interface ScheduleEndBlock {
    type: ScheduleEndType;
    date_time: string | null;
    max_runs: number | null;
}

/** Fully-configured schedule block used in create/update request bodies. */
export interface ScheduleBlock {
    run_mode: ScheduleRunMode;
    start_date_time: string;
    interval: ScheduleIntervalBlock | null;
    end: ScheduleEndBlock;
    timezone: string;
}

// ── Response-side types (nullable sub-fields for draft nodes) ────────────────

/** Interval block as returned by the API — every/unit are null on draft nodes. */
export interface GetScheduleIntervalBlock {
    every: number | null;
    unit: ScheduleIntervalUnit | null;
    weekdays: WeekdayCode[];
}

/** End block as returned by the API — type is null on draft nodes. */
export interface GetScheduleEndBlock {
    type: ScheduleEndType | null;
    date_time: string | null;
    max_runs: number | null;
}

/**
 * Schedule block as returned by GET/POST/PUT/PATCH responses.
 * run_mode and start_date_time are null for draft nodes (is_active=false, schedule not yet configured).
 */
export interface GetScheduleBlock {
    run_mode: ScheduleRunMode | null;
    timezone: string;
    start_date_time: string | null;
    next_run_date_time: string | null;
    interval: GetScheduleIntervalBlock | null;
    end: GetScheduleEndBlock;
}

// ── HTTP DTOs ────────────────────────────────────────────────────────────────

/** Shape returned by GET /api/schedule-trigger-nodes/{id}/ and as the response body of POST/PUT/PATCH. */
export interface GetScheduleTriggerNodeRequest {
    id: number;
    node_name: string;
    graph: number;
    is_active: boolean;
    metadata: Record<string, unknown>;
    content_hash: string;
    created_at: string;
    updated_at: string;
    current_runs: number;
    schedule: GetScheduleBlock | null;
}

/** Request body for POST /api/schedule-trigger-nodes/ and PUT /api/schedule-trigger-nodes/{id}/. Omit or null schedule to create/reset a draft. */
export interface CreateScheduleTriggerNodeRequest {
    node_name: string;
    graph: number;
    is_active?: boolean;
    metadata?: Record<string, unknown>;
    schedule?: ScheduleBlock | null;
}

/** Request body for PATCH /api/schedule-trigger-nodes/{id}/. Send schedule: null to clear the schedule and revert to draft. */
export interface PatchScheduleTriggerNodeRequest {
    node_name?: string;
    is_active?: boolean;
    metadata?: Record<string, unknown>;
    schedule?: ScheduleBlock | null;
}

/** Internal frontend node.data shape for the Schedule Trigger node. Separate from the backend DTO. */
export interface ScheduleTriggerNodeData {
    isActive: boolean;
    runMode: ScheduleRunMode;
    startDateTime: string;
    intervalEvery: number | null;
    intervalUnit: ScheduleIntervalUnit | null;
    weekdays: WeekdayCode[];
    endType: ScheduleEndType;
    endDateTime: string | null;
    maxRuns: number | null;
    currentRuns?: number;
    timezone: string;
    nextRunDateTime?: string | null;
}
