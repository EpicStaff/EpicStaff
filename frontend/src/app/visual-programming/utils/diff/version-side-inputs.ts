import { RestoreWarning } from '../../../features/flows/models/graph.model';
import { SnapshotNode } from '../../../features/flows/models/graph-version-preview.model';
import { FieldName } from './field-display';
import { MissingReference, VersionKeyValueTableNames, VersionWarningReferences } from './types';

// The version-side inputs of `buildFlowDiff`, built from the preview response. Each builder takes the
// `snapshotIdToCanvasId` map returned by `buildPreviewFlowModel`.

/**
 * Backend field of a `secret_declaration_dropped` warning → projected path of the secret it declared.
 * Python and webhook code both project to `python_code`; a classification table projects its code as
 * `pre_computation` / `post_computation`.
 */
const SECRET_DECLARATION_PATHS: ReadonlyMap<string, FieldName> = new Map<string, FieldName>([
    ['python_code', 'python_code.secret_names'],
    ['pre_python_code', 'pre_computation.secret_names'],
    ['post_python_code', 'post_computation.secret_names'],
    ['telegram_bot_api_key_secret', 'telegram_bot_api_key_secret_id'],
]);

/**
 * The references the preview filtering removed from the version, by version canvas node id. A restore
 * runs the same filter and name lookup, so these cannot come back. Only node-anchored warnings count;
 * the others (`edge_dropped`, `node_type_unsupported`) belong to the warnings banner.
 * - `fk_nulled`: its `field` (`agent_definition`, `webhook_trigger`, `subgraph`, the projected path) and `missing_id`
 * - `decision_table_ref_cleared`: the route field it names and `missing_node_id`
 * - `surface_dropped`: `surface_list` and the surface id
 * - `inline_tool_dropped`: the whole `inline_surface` (the warning names no field) and the tool id
 * - `secret_declaration_dropped`: the secret field of the code (or bot key) it names and `missing_name`
 */
export function buildVersionWarningReferences(
    warnings: readonly RestoreWarning[],
    snapshotIdToCanvasId: ReadonlyMap<number, string>
): VersionWarningReferences {
    const references = new Map<string, MissingReference[]>();
    for (const warning of warnings) {
        if (warning.node_id == null) continue;
        const canvasId = snapshotIdToCanvasId.get(warning.node_id);
        const reference = referenceOf(warning);
        if (canvasId === undefined || reference === null) continue;
        references.set(canvasId, [...(references.get(canvasId) ?? []), reference]);
    }
    return references;
}

/** The table names the snapshot stored on Key-Value nodes, by version canvas node id. */
export function buildVersionKeyValueTableNames(
    snapshotNodes: readonly SnapshotNode[],
    snapshotIdToCanvasId: ReadonlyMap<number, string>
): VersionKeyValueTableNames {
    const tableNames = new Map<string, string>();
    for (const node of snapshotNodes) {
        if (node.node_type !== 'KeyValueNode' || !node.key_value_table_name) continue;
        const canvasId = snapshotIdToCanvasId.get(node.id);
        if (canvasId !== undefined) tableNames.set(canvasId, node.key_value_table_name);
    }
    return tableNames;
}

function referenceOf(warning: RestoreWarning): MissingReference | null {
    switch (warning.type) {
        case 'fk_nulled':
            return warning.field ? fromWarning(warning.field, warning.field, warning.missing_id) : null;
        case 'decision_table_ref_cleared': {
            const route = warning.field ? decisionTableRoute(warning.field) : null;
            return route ? fromWarning(route.path, route.field, warning.missing_node_id) : null;
        }
        case 'surface_dropped':
            return fromWarning('surface_list', 'surface_list' satisfies FieldName, warning.missing_id);
        case 'inline_tool_dropped':
            return fromWarning('inline_surface', 'inline_surface' satisfies FieldName, warning.missing_id);
        case 'secret_declaration_dropped': {
            const path = warning.field ? SECRET_DECLARATION_PATHS.get(warning.field) : undefined;
            return path ? fromWarning(path, path, warning.missing_name) : null;
        }
        default:
            return null;
    }
}

function fromWarning(path: string, field: string, missing: number | string | undefined): MissingReference {
    return { path, field, missing: missing ?? null, source: 'warning' };
}

/**
 * Backend route field names → projected paths (`condition_groups[yes].next_node_id` →
 * `condition_groups[name=yes].next_node`). The warning names the raw group name, so with repeated
 * group names the path points at the first group of that name.
 */
function decisionTableRoute(backendField: string): { path: string; field: string } | null {
    if (backendField === 'default_next_node_id') {
        return { path: 'default_next_node', field: 'default_next_node' satisfies FieldName };
    }
    if (backendField === 'next_error_node_id') {
        return { path: 'next_error_node', field: 'next_error_node' satisfies FieldName };
    }
    const groupRoute = /^condition_groups\[(.*)\]\.next_node_id$/.exec(backendField);
    const groupRouteField: FieldName = 'condition_groups[].next_node';
    return groupRoute
        ? { path: groupRouteField.replace('[]', `[name=${groupRoute[1]}]`), field: groupRouteField }
        : null;
}
