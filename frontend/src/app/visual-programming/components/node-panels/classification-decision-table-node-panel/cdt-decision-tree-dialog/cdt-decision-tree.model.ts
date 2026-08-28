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

/**
 * The five legend shapes, plus the region outline.
 *
 * `region` is not a flowchart symbol and stays out of the legend: it is the
 * boundary drawn around the rules, and it exists as a block only so that Foblex
 * has a real element to hang the `Error` connector on.
 */
export type CdtTreeShape = 'terminator' | 'predefined-process' | 'data' | 'decision' | 'process' | 'region';

export type CdtTreeBlockKind =
    | 'table-entered'
    | 'pre-computation'
    | 'read-variables'
    | 'rules-region'
    | 'row-decision'
    | 'row-prompt'
    | 'row-manipulation'
    | 'post-computation'
    | 'exit-terminator';

export type CdtTreePortSide = 'top' | 'right' | 'bottom' | 'left';

export type CdtTreeEdgeKind = 'flow' | 'yes' | 'no' | 'default' | 'error' | 'continue';

/** Full content of a block, shown in the read-only detail window. */
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
     * Full content, shown in the read-only detail window and matched by the search.
     *
     * Deliberately not the clickability flag: a block can carry content worth
     * finding without being one the design lets you open.
     */
    readonly detail: CdtTreeDetail | null;
    /** Whether clicking opens the detail window — see `CLICKABLE_BY_KIND`. */
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

/**
 * A row's `yes` branch: blocks running right from the diamond, centred on it and
 * right-aligned with every other chain, so the branches form columns and the
 * strip past their shared right edge stays free for the exit edges.
 */
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

/** One column of the exit row: a vertical stack, and how its x is decided. */
export interface CdtTreeExitColumn {
    readonly blockIds: readonly string[];
    /**
     * Each anchor names the thing the column's edge comes down from, so that edge
     * is a straight vertical drop: `spine` centres it on the column above,
     * `region` on the rules region whose bottom the `Error` edge leaves, and
     * `chain-corridor` on the clear strip every chain exit drops through.
     *
     * A column never moves left of the one before it, whatever its anchor says.
     */
    readonly anchor: 'spine' | 'region' | 'chain-corridor';
}

/**
 * The row of exits: default, error and the shared route lane.
 *
 * Placed below everything else on the canvas rather than below a named block —
 * the rules region reaches lower than the last rule, and the row has to clear it.
 */
export interface CdtTreeExitsLane {
    readonly kind: 'exits';
    readonly columns: readonly CdtTreeExitColumn[];
}

/**
 * The outline drawn around the rules.
 *
 * It has no size of its own — the layout gives it the bounds of everything it
 * covers, plus padding. It is a block rather than decoration because the `Error`
 * edge leaves the region as a whole, and Foblex needs a real element to attach
 * that connector to.
 */
export interface CdtTreeRegionLane {
    readonly kind: 'region';
    readonly blockId: string;
    readonly coversIds: readonly string[];
}

/**
 * A lane is the unit the layout places.
 *
 * Naming one block id per arrangement on `CdtTree` did not scale: every new
 * branch that left the column meant another field and another `if` in the layout.
 * A new arrangement is now a new variant here, and the exhaustive switch makes
 * the layout state what it does with it.
 */
export type CdtTreeLane = CdtTreeSpineLane | CdtTreeChainLane | CdtTreeAsideLane | CdtTreeExitsLane | CdtTreeRegionLane;

/**
 * One heading of the search dropdown, and the blocks under it in reading order.
 *
 * Built alongside the lanes, from the same locals, because it is the only place
 * that knows the order a person reads the diagram in: `blocks` is construction
 * order, which puts the exits before the rules, and the layout throws the lanes
 * away. Deriving it anywhere else would mean parsing block ids.
 */
export interface CdtTreeGroup {
    readonly label: string;
    readonly blockIds: readonly string[];
}

export interface CdtTree {
    readonly title: string;
    readonly blocks: readonly CdtTreeBlock[];
    readonly edges: readonly CdtTreeEdge[];
    /** Entry, then one per drawn rule, then Exit. The region belongs to none. */
    readonly groups: readonly CdtTreeGroup[];
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

/**
 * One Foblex connector on a block, created for exactly one edge endpoint.
 *
 * Every connector sits at the centre of its side — the apex of a diamond, the
 * middle of every other shape. Fanning them along the side was tried and undone:
 * it moved an edge's two ends off the axis they share, which bent every drop down
 * the spine into a dog-leg, and a flowchart's edges have to read as straight.
 * Several edges arriving at one block therefore meet at a single point, which is
 * how the mockup draws a convergence anyway.
 */
export interface CdtTreeConnector {
    readonly id: string;
    readonly side: CdtTreePortSide;
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
    /** Passed through untouched — the layout has no say in reading order. */
    readonly groups: readonly CdtTreeGroup[];
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
