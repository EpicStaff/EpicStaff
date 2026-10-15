import { AgentSearchConfigs, DeclaredSecretRef, GetPythonCodeRequest } from '@shared/models';

import {
    SnapshotClassificationPythonCode,
    SnapshotInlineSurface,
    SnapshotKnowledgeNode,
    SnapshotPythonCode,
    SnapshotScheduleTriggerNode,
} from '../../../../features/flows/models/graph-version-preview.model';
import { CDTPythonCodeBlock } from '../../../core/models/classification-decision-table-node.model';
import {
    GetScheduleBlock,
    ScheduleEndType,
    ScheduleIntervalUnit,
    ScheduleRunMode,
    WeekdayCode,
} from '../../../core/models/schedule-trigger.model';
import { InlineSurface } from '../../../core/models/task-node.model';

/**
 * Field adapters from the version-snapshot (export) shape to the live GraphDto shape — one per
 * difference, so a node adapter reads as a list of the fields that differ.
 */

/** Space-separated library string (export) → list (live). */
export function parseSnapshotLibraries(libraries: string | null | undefined): string[] {
    return (libraries ?? '').split(' ').filter(Boolean);
}

/**
 * Declared secret names → live refs. A name the organisation no longer has is left out, the same
 * as a secret deleted after the node was saved; the restore warnings report it.
 */
export function resolveDeclaredSecrets(
    names: readonly string[] | undefined,
    secretsByName: ReadonlyMap<string, number>
): DeclaredSecretRef[] {
    return (names ?? []).flatMap((name) => {
        const id = secretsByName.get(name);
        return id === undefined ? [] : [{ id, name }];
    });
}

/** A single secret stored by name in the snapshot (e.g. the Telegram bot key) → its live id. */
export function resolveSecretIdByName(
    name: string | null | undefined,
    secretsByName: ReadonlyMap<string, number>
): number | null {
    return name ? (secretsByName.get(name) ?? null) : null;
}

/** Export python code (no id, library string) → live python code. */
export function toLivePythonCode(code: SnapshotPythonCode, secrets: DeclaredSecretRef[]): GetPythonCodeRequest {
    return {
        id: 0,
        code: code.code,
        entrypoint: code.entrypoint,
        libraries: parseSnapshotLibraries(code.libraries),
        secrets,
    };
}

/** Export CDT pre/post code (library string) → live CDT code block. */
export function toLiveClassificationPythonCode(
    code: SnapshotClassificationPythonCode | null,
    secrets: DeclaredSecretRef[]
): CDTPythonCodeBlock | null {
    if (!code) return null;
    return { ...code, libraries: parseSnapshotLibraries(code.libraries), secrets };
}

/**
 * Export `inline_surface` → live `InlineSurface`. The export keeps only instructions and tool
 * assignments, so storage items and knowledge are empty in a preview. A tool whose reference the
 * backend nulled (it no longer exists) cannot be shown and is left out; the node itself stays.
 */
export function toLiveInlineSurface(exported: SnapshotInlineSurface | null | undefined): InlineSurface | null {
    if (!exported) return null;
    return {
        instructions: exported.instructions,
        python_tools: (exported.tools.PythonCodeTool ?? []).flatMap((tool) =>
            tool.python_tool_id === null ? [] : [{ python_tool: tool.python_tool_id, mode: tool.mode }]
        ),
        mcp_tools: (exported.tools.MCPTool ?? []).flatMap((tool) =>
            tool.mcp_tool_id === null ? [] : [{ mcp_tool: tool.mcp_tool_id, mode: tool.mode }]
        ),
        storage_items: [],
        knowledge: [],
    };
}

/**
 * Knowledge node search configs. The export writes the similarity threshold as a Decimal string;
 * the live API sends `round(float(value), 2)` (backend `SearchConfigService.get_node_search_configs`).
 */
export function toLiveSearchConfigs(node: SnapshotKnowledgeNode): AgentSearchConfigs | null {
    const configs: AgentSearchConfigs = {};

    const naive = node.naive_search_config;
    if (naive) {
        configs.naive = {
            search_limit: naive.search_limit,
            similarity_threshold: toRoundedNumber(naive.similarity_threshold),
            is_suggested: naive.is_suggested,
        };
    }

    const graphConfigs = {
        basic: node.graph_basic_search_config ?? null,
        local: node.graph_local_search_config ?? null,
        global: node.graph_global_search_config ?? null,
        drift: node.graph_drift_search_config ?? null,
    };
    if (Object.values(graphConfigs).some((config) => config !== null)) {
        configs.graph = { search_method: node.search_method ?? 'basic', ...graphConfigs };
    }

    return configs.naive || configs.graph ? configs : null;
}

/**
 * Builds the live `schedule` block from the snapshot's flat columns.
 *
 * Mirrors backend `ScheduleTriggerValidator.render_to_representation` and
 * `format_utc_to_local_naive_iso` (src/django_app/tables/validators/schedule_trigger_validator.py)
 * and must stay in sync with them. Unlike the live API, `next_run_date_time` is always null: a
 * preview never runs.
 */
export function buildScheduleBlock(node: SnapshotScheduleTriggerNode): GetScheduleBlock {
    const timeZone = node.timezone || 'UTC';
    return {
        run_mode: node.run_mode as ScheduleRunMode | null,
        timezone: timeZone,
        start_date_time: toLocalNaiveIso(node.start_date_time, timeZone),
        next_run_date_time: null,
        interval:
            node.run_mode === 'once'
                ? null
                : {
                      every: node.every,
                      unit: node.unit as ScheduleIntervalUnit | null,
                      weekdays: (node.weekdays ?? []) as WeekdayCode[],
                  },
        end: {
            type: node.end_type as ScheduleEndType | null,
            date_time: toLocalNaiveIso(node.end_date_time, timeZone),
            max_runs: node.max_runs,
        },
    };
}

/**
 * An offset ISO datetime → the wall-clock time in `timeZone`, as a naive ISO string
 * (`2026-07-01T09:00:00Z`, Europe/Kyiv → `2026-07-01T12:00:00`). Like Python's `isoformat()`,
 * fractional seconds are written (6 digits) only when non-zero. An unknown zone falls back to UTC.
 */
export function toLocalNaiveIso(isoDateTime: string | null, timeZone: string): string | null {
    if (!isoDateTime) return null;
    const date = new Date(isoDateTime);
    if (Number.isNaN(date.getTime())) return null;

    const parts = formatPartsInZone(date, timeZone);
    const part = (type: Intl.DateTimeFormatPartTypes): string => parts.find((p) => p.type === type)?.value ?? '';
    const wallClock = `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}:${part('second')}`;

    const microseconds = (/\.(\d+)/.exec(isoDateTime)?.[1] ?? '').padEnd(6, '0').slice(0, 6);
    return /^0*$/.test(microseconds) ? wallClock : `${wallClock}.${microseconds}`;
}

function formatPartsInZone(date: Date, timeZone: string): Intl.DateTimeFormatPart[] {
    const options: Intl.DateTimeFormatOptions = {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hourCycle: 'h23',
    };
    try {
        return new Intl.DateTimeFormat('en-CA', { ...options, timeZone }).formatToParts(date);
    } catch {
        return new Intl.DateTimeFormat('en-CA', { ...options, timeZone: 'UTC' }).formatToParts(date);
    }
}

function toRoundedNumber(value: string | null): number | null {
    if (value === null) return null;
    return Math.round(Number(value) * 100) / 100;
}
