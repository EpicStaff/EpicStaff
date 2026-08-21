/**
 * Types for the read-only Decision Tree view of a Classification Decision Table node.
 *
 * The diagram is derived from the node on every open and never persisted, so every
 * type here is `readonly` end to end — the dialog is structurally unable to mutate it.
 *
 * No Angular dependencies: the builder and the layout pass that produce these types
 * are pure functions, unit-tested without TestBed.
 */

import { PromptConfig } from '../../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../../core/models/decision-table.model';

// ---------------------------------------------------------------------------
// Input snapshot
// ---------------------------------------------------------------------------

/**
 * Minimal shape of a canvas node needed to resolve a routing target's label.
 * `NodeModel` satisfies this structurally.
 */
export interface CdtTreeNodeRef {
    readonly id: string;
    readonly node_name: string;
    readonly backendId: number | null;
    readonly nodeNumber?: number;
}

/**
 * Minimal shape of a canvas connection needed for the routing fallback scan.
 * `ConnectionModel` satisfies this structurally.
 */
export interface CdtTreeConnectionRef {
    readonly sourceNodeId: string;
    readonly sourcePortId: string;
    readonly targetNodeId: string;
}

/**
 * A frozen snapshot of everything the diagram needs, taken when the dialog opens.
 *
 * `rows` comes from the panel's clone (it carries unsaved grid edits) while
 * `canvasRows` comes from the live canvas node (it carries the `next_node` values
 * FlowService writes). Neither copy has both halves — see `resolveRowTarget`.
 */
export interface CdtDecisionTreeInput {
    readonly nodeId: string;
    readonly nodeName: string;
    readonly preCode: string;
    readonly postCode: string;
    readonly preInputMap: Readonly<Record<string, string>>;
    readonly prompts: Readonly<Record<string, PromptConfig>>;
    readonly rows: readonly ConditionGroup[];
    readonly canvasRows: readonly ConditionGroup[];
    /** Already resolved to a canvas node id by the panel's `initializeForm`. */
    readonly defaultNextNode: string | null;
    /** Already resolved to a canvas node id by the panel's `initializeForm`. */
    readonly errorNextNode: string | null;
    readonly connections: readonly CdtTreeConnectionRef[];
    readonly nodes: readonly CdtTreeNodeRef[];
}

// ---------------------------------------------------------------------------
// Tree model
// ---------------------------------------------------------------------------

/** The five shapes of the mockup's legend. */
export type CdtTreeShape = 'terminator' | 'predefined-process' | 'data' | 'decision' | 'process';

export type CdtTreeBlockKind =
    | 'table-entered'
    | 'pre-computation'
    | 'read-variables'
    | 'row-decision'
    | 'row-prompt'
    | 'row-manipulation'
    | 'row-continue'
    | 'row-captured'
    | 'default-continue'
    | 'error-continue'
    | 'post-computation'
    | 'table-left';

export type CdtTreePortSide = 'top' | 'right' | 'bottom' | 'left';

export type CdtTreeEdgeKind = 'flow' | 'yes' | 'no' | 'error' | 'continue';

/** Full content of a block, shown in the read-only popover. */
export interface CdtTreeDetail {
    readonly heading: string;
    readonly language: 'python' | 'text';
    readonly body: string;
}

/**
 * Where a routing block's target resolved — the state, not the sentence.
 *
 * The builder emits this and renders the wording from `CDT_TREE_COPY`, so a
 * rewording changes copy and nothing else, and a test can assert what the diagram
 * means rather than how it is phrased.
 */
export type CdtTreeTarget =
    | { readonly state: 'node'; readonly label: string }
    /** Has a route code, but no target is set anywhere — the table default applies. */
    | { readonly state: 'no-capture' }
    /** No route code at all, so the target is never persisted (see `payload.ts`). */
    | { readonly state: 'unrouted' }
    /** Nothing attached to this output — the graph ends here. */
    | { readonly state: 'end' };

export interface CdtTreeBlock {
    /** Stable within one build, e.g. `row-2:decision` or `spine:pre-computation`. */
    readonly id: string;
    readonly kind: CdtTreeBlockKind;
    readonly title: string;
    readonly subtitle: string | null;
    /**
     * Full content, shown in the read-only popover and matched by the search.
     *
     * Deliberately not the clickability flag: a block can carry content worth
     * finding without being one the design lets you open.
     */
    readonly detail: CdtTreeDetail | null;
    /** Whether clicking opens the popover — see `CLICKABLE_BY_KIND`. */
    readonly clickable: boolean;
    /** Set on the blocks that name a routing target; null on every other block. */
    readonly target: CdtTreeTarget | null;
    /** Non-null renders a warning badge carrying this text as its tooltip. */
    readonly warning: string | null;
    /** Small chip rendered next to the title, e.g. a shared route code. */
    readonly chip: string | null;
    /** Lowercased title + subtitle + detail body, matched by the toolbar search. */
    readonly searchText: string;
}

export interface CdtTreeEdge {
    readonly id: string;
    readonly from: string;
    readonly fromSide: CdtTreePortSide;
    readonly to: string;
    readonly toSide: CdtTreePortSide;
    readonly kind: CdtTreeEdgeKind;
    readonly label: string | null;
}

/**
 * The one vertical column, top to bottom.
 *
 * The builder knows this order naturally; deriving it in the layout would mean
 * parsing ids.
 */
export interface CdtTreeSpineLane {
    readonly kind: 'spine';
    readonly blockIds: readonly string[];
}

/** A row's `yes` branch: blocks running right from the diamond, centred on it. */
export interface CdtTreeChainLane {
    readonly kind: 'chain';
    readonly anchorId: string;
    readonly blockIds: readonly string[];
}

/** A branch that leaves the column sideways, level with its anchor. */
export interface CdtTreeAsideLane {
    readonly kind: 'aside';
    readonly side: 'left' | 'right';
    readonly anchorId: string;
    readonly blockIds: readonly string[];
}

/**
 * A lane is the unit the layout places.
 *
 * Naming one block id per arrangement on `CdtTree` did not scale: every new
 * branch that left the column meant another field and another `if` in the layout.
 * A new arrangement is now a new variant here, and the exhaustive switch makes
 * the layout state what it does with it.
 */
export type CdtTreeLane = CdtTreeSpineLane | CdtTreeChainLane | CdtTreeAsideLane;

export interface CdtTree {
    readonly title: string;
    readonly blocks: readonly CdtTreeBlock[];
    readonly edges: readonly CdtTreeEdge[];
    /**
     * Where every block goes: exactly one `spine` lane, one `chain` per drawn row
     * in evaluation order, and an `aside` per branch that leaves the column.
     */
    readonly lanes: readonly CdtTreeLane[];
    /** Rows excluded because `dock_visible === false`; surfaced in the toolbar. */
    readonly hiddenRowCount: number;
    /** Rows actually drawn. */
    readonly rowCount: number;
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

export interface CdtTreePoint {
    readonly x: number;
    readonly y: number;
}

export interface CdtTreeSize {
    readonly width: number;
    readonly height: number;
}

/** One Foblex connector on a block, created for exactly one edge endpoint. */
export interface CdtTreeConnector {
    readonly id: string;
    readonly side: CdtTreePortSide;
    /**
     * Where along that side the connector sits, 0 to 1.
     *
     * Per-edge connectors stop two edges from sharing one, but not from arriving
     * at the same pixel: every connector used to sit at the side's midpoint, so a
     * convergence of N edges drew N paths into one point. Foblex measures the
     * connector element, so spreading them here spreads the arrows.
     */
    readonly offset: number;
}

export interface CdtTreePositionedBlock extends CdtTreeBlock {
    readonly shape: CdtTreeShape;
    readonly position: CdtTreePoint;
    readonly size: CdtTreeSize;
    readonly outPorts: readonly CdtTreeConnector[];
    readonly inPorts: readonly CdtTreeConnector[];
}

export interface CdtTreeLayout {
    readonly title: string;
    readonly blocks: readonly CdtTreePositionedBlock[];
    readonly edges: readonly CdtTreeEdge[];
    readonly bounds: CdtTreeSize;
    readonly hiddenRowCount: number;
    readonly rowCount: number;
}

// ---------------------------------------------------------------------------
// Connector ids
// ---------------------------------------------------------------------------

/**
 * Connectors are created **per edge**, not per side.
 *
 * A flowchart converges — several rules can route to the same block, and the
 * fall-through block is the target of both the last rule's `no` edge and any
 * `continue` rejoin. Sharing one connector between two edges makes Foblex drop
 * the colliding edge *and every edge declared after it*, with no path rendered
 * and nothing logged. Keying the connector by edge id makes collisions
 * impossible by construction.
 */
export function outputConnectorId(edgeId: string): string {
    return `${edgeId}::out`;
}

export function inputConnectorId(edgeId: string): string {
    return `${edgeId}::in`;
}
