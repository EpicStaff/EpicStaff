import { NodeType } from '@shared/models';

import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';

/**
 * How a field value is shown:
 * - `scalar`: a short single value (name, flag, enum, number)
 * - `text`: free or code text (instructions, python code, expressions)
 * - `entityRef`: the id of a linked entity (agent definition, LLM config, subflow, trigger, table, collection)
 * - `nodeRef`: the match key of another node of the same flow (`FlowDiff.nodes[].key`)
 * - `list`: a normalized list (sorted when order does not matter)
 * - `json`: a structured value (maps, schemas, a whole list item)
 */
export type FieldKind = 'scalar' | 'text' | 'entityRef' | 'nodeRef' | 'list' | 'json';

/**
 * What a restore of the version does to the field: `added` = the field or item is in the version only,
 * `deleted` = on the current canvas only, `changed` = on both sides with different values.
 */
export type FieldChangeStatus = 'added' | 'deleted' | 'changed';

export interface FieldChange {
    /** Concrete, load-independent path, e.g. `python_code.code` or `condition_groups[name=yes].next_node`. */
    path: string;
    /** `path` without item keys, e.g. `condition_groups[].next_node`: the key into `FIELD_DISPLAY`. */
    field: string;
    status: FieldChangeStatus;
    /** The current canvas value (`null` when the field or item is not on the canvas). */
    current: unknown;
    /** The version value, i.e. what a restore writes (`null` when the field or item is not in the version). */
    version: unknown;
}

/**
 * Where a missing reference was found:
 * - `warning`: a node-anchored preview warning (deleted secrets included); the backend warnings dialog
 *   already lists it;
 * - `keyValueTable`: a Key-Value table name the version stored that no usable table has now. The backend
 *   re-binds the table without a warning, so only the frontend finds it.
 */
export type MissingReferenceSource = 'warning' | 'keyValueTable';

/**
 * Something the version referenced that no longer exists, so a restore cannot bring it back.
 * The version value of the field is the filtered one (the reference already removed), which is what a
 * restore writes; this record keeps what was lost.
 */
export interface MissingReference {
    /** Projected path of the field that held the reference, like `FieldChange.path`. */
    path: string;
    /**
     * `path` without item keys: the key into `FIELD_DISPLAY`. A field that is not a `FieldName` (a venv of table
     * code) anchors no panel note: the reference only marks the node on the canvas.
     */
    field: string;
    /** The id (entity or node) or the name (secret, table) the version had; `null` when the warning lacks it. */
    missing: number | string | null;
    source: MissingReferenceSource;
}

/**
 * What a restore of the version does to the node: `added` = in the version only (a restore adds it),
 * `deleted` = on the canvas only (a restore removes it), `changed` = matched with at least one field change.
 */
export type NodeDiffStatus = 'added' | 'deleted' | 'changed' | 'unchanged';

/** `uuid`: same stable node uuid. `start`: the Start nodes of both sides, paired by type. */
export type NodeMatchKind = 'uuid' | 'start';

export interface NodeDiffEntry {
    /** Stable key of the node across both sides; node references and edges use it. */
    key: string;
    /** How the two sides were paired; `null` for an added or deleted node. */
    matchedBy: NodeMatchKind | null;
    status: NodeDiffStatus;
    type: NodeType;
    /** The node in the version; absent for a deleted (canvas-only) node. */
    versionNode?: NodeModel;
    /** The node on the current canvas; absent for an added (version-only) node. */
    currentNode?: NodeModel;
    /** Field changes of a matched node. Empty for added and deleted nodes. */
    fields: readonly FieldChange[];
    /**
     * What the version referenced that no longer exists. Filled for every node with a version side
     * (matched and added), empty for deleted nodes. It never changes `status`.
     */
    missingReferences: readonly MissingReference[];
}

/** `added` = in the version only (a restore adds it), `deleted` = on the canvas only (a restore removes it). */
export type EdgeDiffStatus = 'added' | 'deleted' | 'unchanged';

/** `edge`: a plain edge. `dt-route` / `cdt-route`: a decision-table route, stored as a field of its node. */
export type EdgeRouteKind = 'edge' | 'dt-route' | 'cdt-route';

export interface EdgeDiffEntry {
    /**
     * Unique within one diff only: it is built from node match keys, and the key of an added or
     * deleted node contains its canvas id. Compare edges across diffs by endpoints and route.
     */
    key: string;
    status: EdgeDiffStatus;
    sourceKey: string;
    targetKey: string;
    routeKind: EdgeRouteKind;
    /** Semantic source port of a route: `group:<group name>`, `default` or `error`. `null` for a plain edge. */
    route: string | null;
}

export interface FlowDiffSummary {
    added: number;
    deleted: number;
    changed: number;
    unchanged: number;
    edgesAdded: number;
    edgesDeleted: number;
}

export interface FlowDiff {
    /** Version nodes first (in version order), then nodes only on the current canvas. */
    nodes: readonly NodeDiffEntry[];
    edges: readonly EdgeDiffEntry[];
    summary: FlowDiffSummary;
    /**
     * Share of the version's non-Start nodes matched by uuid (0..1); 1 when the version has none.
     * Start nodes are left out because they are paired by type anyway. 0 while both sides have
     * nodes means the version predates node uuids.
     */
    matchRate: number;
}

/** Missing references taken from the preview warnings, by version canvas node id. */
export type VersionWarningReferences = ReadonlyMap<string, readonly MissingReference[]>;

/** The Key-Value table name the snapshot stored, by version canvas node id (only nodes that had one). */
export type VersionKeyValueTableNames = ReadonlyMap<string, string>;

/**
 * The version-side inputs only feed `NodeDiffEntry.missingReferences`; they never change a status or a
 * field value. They are required on purpose: a forgotten one would silently drop missing references.
 * A flow-to-flow comparison passes empty maps.
 */
export interface FlowDiffInput {
    /** The previewed version (`buildPreviewFlowModel(...).flow`): what a restore writes. */
    versionFlow: FlowModel;
    /** The current canvas, unsaved edits included. */
    liveFlow: FlowModel;
    /**
     * From `buildVersionWarningReferences`: the references the preview filtering removed (ids) and the
     * declared secrets the backend could not resolve (names).
     */
    versionWarningReferences: VersionWarningReferences;
    /**
     * From `buildVersionKeyValueTableNames`. The preview and restore re-bind a Key-Value node's table by
     * this name and set it to null, with no warning, when no table of that name is usable; that name is
     * then a missing reference.
     */
    versionKeyValueTableNames: VersionKeyValueTableNames;
}
