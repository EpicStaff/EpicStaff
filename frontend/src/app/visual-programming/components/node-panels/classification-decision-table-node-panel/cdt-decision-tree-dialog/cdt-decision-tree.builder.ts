/**
 * Pure builder: a Classification Decision Table snapshot → the blocks and edges of
 * its execution flowchart. No coordinates — the layout pass adds those.
 *
 * The block sequence mirrors the engine documented in
 * `docs/classification_decision_table/classification_decision_table.md`, so the
 * diagram is a faithful drawing of what actually runs rather than an interpretation.
 */

import { ConditionGroup } from '../../../../core/models/decision-table.model';
import {
    composeExpression,
    composeManipulation,
    normalizeOpPart,
    parseExpression,
    parseManipulation,
    toDisplayExpression,
} from '../../../../utils/condition-expression.helper';
import {
    CDT_TREE_SUBTITLE_CODE_LINES,
    CDT_TREE_SUBTITLE_MAX_CHARS,
    CLICKABLE_BY_KIND,
} from './cdt-decision-tree.constants';
import {
    CdtDecisionTreeInput,
    CdtTree,
    CdtTreeBlock,
    CdtTreeBlockKind,
    CdtTreeChainLane,
    CdtTreeDetail,
    CdtTreeEdge,
    CdtTreeEdgeKind,
    CdtTreeNodeRef,
    CdtTreePortSide,
} from './cdt-decision-tree.model';

/** Where a row's routing target ended up resolving. */
type CdtRowTarget =
    | { readonly kind: 'node'; readonly label: string }
    /** Has a route code, but no target is set anywhere — the table default applies. */
    | { readonly kind: 'no-capture' }
    /** No route code at all, so the target is never persisted (see `payload.ts`). */
    | { readonly kind: 'unrouted' };

const UNROUTED_WARNING = 'This rule has no route code, so its target is never saved.';

export function buildCdtDecisionTree(input: CdtDecisionTreeInput): CdtTree {
    const blocks: CdtTreeBlock[] = [];
    const edges: CdtTreeEdge[] = [];

    const enabledRows = sortRows(input.rows.filter((row) => row.dock_visible !== false));
    const hiddenRowCount = input.rows.length - enabledRows.length;
    const routeCodeCounts = countRouteCodes(enabledRows);
    const canvasRowsByRoute = indexCanvasRowsByRoute(input.canvasRows);

    // -- head of the spine ---------------------------------------------------

    const entered = block(blocks, {
        id: 'spine:table-entered',
        kind: 'table-entered',
        title: 'Table entered',
    });

    const spineHead: string[] = [entered];

    const preCode = input.preCode?.trim() ?? '';
    if (preCode) {
        spineHead.push(
            block(blocks, {
                id: 'spine:pre-computation',
                kind: 'pre-computation',
                title: 'Pre-computation',
                subtitle: codePreview(preCode),
                detail: { heading: 'Pre-computation', language: 'python', body: preCode },
            })
        );
    }

    const inputMapPairs = Object.entries(input.preInputMap ?? {}).filter(([key]) => !!key);
    if (inputMapPairs.length > 0) {
        spineHead.push(
            block(blocks, {
                id: 'spine:read-variables',
                kind: 'read-variables',
                title: 'Read variables',
                subtitle: clamp(inputMapPairs.map(([key, value]) => `${key} → ${value}`).join(', ')),
                detail: {
                    heading: 'Variables bound before evaluation',
                    language: 'text',
                    body: inputMapPairs.map(([key, value]) => `${key} → ${value}`).join('\n'),
                },
            })
        );
    }

    for (let i = 1; i < spineHead.length; i++) {
        edges.push(edge(spineHead[i - 1], 'bottom', spineHead[i], 'top', 'flow'));
    }

    /** Last block before row evaluation — where the rows and the error lane hang off. */
    const beforeRows = spineHead[spineHead.length - 1];

    // -- tail of the spine, created up front so rows can wire into it --------

    const fallThrough = block(blocks, {
        ...fallThroughContent(input),
        id: 'spine:default-continue',
        kind: 'default-continue',
    });

    const postCode = input.postCode?.trim() ?? '';
    const post = postCode
        ? block(blocks, {
              id: 'spine:post-computation',
              kind: 'post-computation',
              title: 'Post-computation',
              subtitle: codePreview(postCode),
              detail: { heading: 'Post-computation', language: 'python', body: postCode },
          })
        : null;

    const left = block(blocks, {
        id: 'spine:table-left',
        kind: 'table-left',
        title: 'Data leaves the table',
    });

    /** Every route block converges here, exactly as the mockup draws it. */
    const exit = post ?? left;

    edges.push(edge(fallThrough, 'bottom', exit, 'top', 'flow'));
    if (post) {
        edges.push(edge(post, 'bottom', left, 'top', 'flow'));
    }

    // -- error lane ----------------------------------------------------------

    const error = block(blocks, {
        ...targetContent(input.errorNextNode, input.nodes, 'Errors end the flow'),
        id: 'spine:error-continue',
        kind: 'error-continue',
    });
    // Any step of row evaluation can raise, so the branch hangs off the last block
    // before the rows rather than off a single rule.
    edges.push(edge(beforeRows, 'left', error, 'top', 'error', 'on error'));
    edges.push(edge(error, 'bottom', exit, 'left', 'flow'));

    // -- one branch per enabled row -----------------------------------------

    const chains: CdtTreeChainLane[] = [];

    enabledRows.forEach((row, index) => {
        const decision = block(blocks, {
            id: `row-${index}:decision`,
            kind: 'row-decision',
            title: row.group_name?.trim() || `Rule ${index + 1}`,
            subtitle: rowExpressionSubtitle(row),
            detail: rowExpressionDetail(row),
            chip: chipForSharedRoute(row, routeCodeCounts),
        });

        // The `no` branch always falls through to the next diamond, or out.
        const next = index + 1 < enabledRows.length ? `row-${index + 1}:decision` : fallThrough;
        edges.push(edge(decision, 'bottom', next, 'top', 'no', 'no'));

        // The `yes` branch chains prompt → manipulation → route, in engine order.
        const chain: string[] = [];

        const prompt = row.prompt_id ? input.prompts?.[row.prompt_id] : undefined;
        if (row.prompt_id) {
            chain.push(
                block(blocks, {
                    id: `row-${index}:prompt`,
                    kind: 'row-prompt',
                    title: prompt ? row.prompt_id : `Prompt "${row.prompt_id}"`,
                    subtitle: prompt ? clamp(prompt.prompt_text) : null,
                    detail: prompt
                        ? {
                              heading: `Prompt "${row.prompt_id}"`,
                              language: 'text',
                              body: promptDetailBody(prompt.prompt_text, prompt.result_variable),
                          }
                        : null,
                    warning: prompt ? null : 'Prompt not found in this table.',
                })
            );
        }

        const manipulation = rowManipulation(row);
        if (manipulation) {
            chain.push(
                block(blocks, {
                    id: `row-${index}:manipulation`,
                    kind: 'row-manipulation',
                    title: 'Set variables',
                    subtitle: clamp(toDisplayExpression(manipulation)),
                    detail: {
                        heading: 'Manipulation',
                        language: 'python',
                        body: toDisplayExpression(manipulation),
                    },
                })
            );
        }

        const target = resolveRowTarget(row, input, canvasRowsByRoute);
        const continues = row.continue_flag ?? row.continue ?? false;

        chain.push(
            continues
                ? block(blocks, {
                      ...capturedContent(target),
                      id: `row-${index}:captured`,
                      kind: 'row-captured',
                  })
                : block(blocks, {
                      ...routeContent(target),
                      id: `row-${index}:route`,
                      kind: 'row-continue',
                  })
        );

        edges.push(edge(decision, 'right', chain[0], 'left', 'yes', 'yes'));
        for (let i = 1; i < chain.length; i++) {
            edges.push(edge(chain[i - 1], 'right', chain[i], 'left', 'flow'));
        }

        // A matched `continue` row does not exit — it rejoins the next diamond.
        // It enters on the right, not the top: the top is already taken by that
        // block's `no` edge, and two edges converging on one point read as one.
        const tail = chain[chain.length - 1];
        edges.push(
            continues
                ? edge(tail, 'bottom', next, 'right', 'continue', 'continue')
                : edge(tail, 'right', exit, 'right', 'flow')
        );

        chains.push({ kind: 'chain', anchorId: decision, blockIds: chain });
    });

    // Enter the ladder at the first rule, or drop straight through when there is none.
    edges.push(
        enabledRows.length > 0
            ? edge(beforeRows, 'bottom', 'row-0:decision', 'top', 'flow')
            : edge(beforeRows, 'bottom', fallThrough, 'top', 'no', 'no row matched')
    );

    return {
        title: input.nodeName,
        blocks,
        edges,
        lanes: [
            {
                kind: 'spine',
                blockIds: [
                    ...spineHead,
                    ...chains.map((chainEntry) => chainEntry.anchorId),
                    fallThrough,
                    ...(post ? [post] : []),
                    left,
                ],
            },
            ...chains,
            // Any step can raise, so the error branch hangs off the column as a
            // whole rather than off one rule.
            { kind: 'aside', side: 'left', anchorId: fallThrough, blockIds: [error] },
        ],
        hiddenRowCount,
        rowCount: enabledRows.length,
    };
}

// ---------------------------------------------------------------------------
// Row content
// ---------------------------------------------------------------------------

/**
 * The combined condition of a row, as the engine builds it: field expressions
 * AND-joined, then the main expression AND-appended.
 *
 * The grid keeps `expression` in sync by recomposing it from `field_expressions`,
 * so joining them blindly renders every clause twice on most rows. Only join when
 * the main expression is genuinely something else.
 */
export function combinedExpression(row: ConditionGroup): string {
    const fields = row.field_expressions ?? {};
    const keys = Object.keys(fields);
    const fieldClauses = composeExpression(fields, keys);
    const main = row.expression?.trim() ?? '';

    if (!main) return fieldClauses;
    if (!fieldClauses) return main;

    const parsed = parseExpression(main);
    const normalized: Record<string, string> = {};
    for (const key of keys) {
        const part = fields[key]?.trim();
        if (part) normalized[key] = normalizeOpPart(part);
    }

    return parsed.ok && sameParts(parsed.parts, normalized) ? main : `${fieldClauses} and ${main}`;
}

/** The combined manipulation of a row, with the same de-duplication as the condition. */
export function rowManipulation(row: ConditionGroup): string {
    const fields = row.field_manipulations ?? {};
    const keys = Object.keys(fields);
    const fieldStatements = composeManipulation(fields, keys);
    const main = row.manipulation?.trim() ?? '';

    if (!main) return fieldStatements;
    if (!fieldStatements) return main;

    const parsed = parseManipulation(main);
    const normalized: Record<string, string> = {};
    for (const key of keys) {
        const part = fields[key]?.trim();
        if (part) normalized[key] = part;
    }

    return parsed.ok && sameParts(parsed.parts, normalized) ? main : `${fieldStatements}; ${main}`;
}

function rowExpressionSubtitle(row: ConditionGroup): string {
    const combined = combinedExpression(row);
    return combined ? clamp(toDisplayExpression(combined)) : 'always matches';
}

function rowExpressionDetail(row: ConditionGroup): CdtTreeDetail | null {
    const combined = combinedExpression(row);
    if (!combined) return null;
    return { heading: 'Condition', language: 'python', body: toDisplayExpression(combined) };
}

function promptDetailBody(promptText: string, resultVariable: string): string {
    const result = resultVariable?.trim();
    return result ? `${promptText}\n\n→ stored in ${result}` : promptText;
}

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

/**
 * Resolve a row's routing target the same way a save would, so the diagram never
 * disagrees with what is about to be persisted:
 * the canvas node's `next_node` first, then the panel clone's, then a scan of the
 * canvas connections by the row's output port id.
 */
function resolveRowTarget(
    row: ConditionGroup,
    input: CdtDecisionTreeInput,
    canvasRowsByRoute: Map<string, ConditionGroup>
): CdtRowTarget {
    const code = row.route_code?.trim();
    if (!code) return { kind: 'unrouted' };

    let targetId = canvasRowsByRoute.get(code)?.next_node ?? row.next_node ?? null;

    if (!targetId) {
        const portId = `${input.nodeId}_decision-route-${slugifyRouteCode(code)}`;
        targetId =
            input.connections.find(
                (connection) => connection.sourceNodeId === input.nodeId && connection.sourcePortId === portId
            )?.targetNodeId ?? null;
    }

    return targetId ? { kind: 'node', label: resolveNodeLabel(targetId, input.nodes) } : { kind: 'no-capture' };
}

/** Mirrors the port id built by `generatePortsForClassificationDecisionTableNode`. */
export function slugifyRouteCode(routeCode: string): string {
    return routeCode.toLowerCase().replace(/\s+/g, '-');
}

/**
 * Resolve a canvas node id to a display label, falling back to `node #<id>` —
 * the same convention the CSV export uses.
 */
export function resolveNodeLabel(targetId: string, nodes: readonly CdtTreeNodeRef[]): string {
    const found = nodes.find((node) => node.id === targetId) ?? nodes.find((node) => node.node_name === targetId);
    if (!found) return `node #${targetId}`;
    return found.node_name?.trim() || `node #${found.nodeNumber ?? found.backendId ?? targetId}`;
}

function routeContent(target: CdtRowTarget): Partial<CdtTreeBlock> {
    switch (target.kind) {
        case 'node':
            return { title: `Continue to ${target.label}` };
        case 'no-capture':
            return { title: 'No target — table default applies' };
        case 'unrouted':
            return { title: 'Not routed', warning: UNROUTED_WARNING };
    }
}

function capturedContent(target: CdtRowTarget): Partial<CdtTreeBlock> {
    switch (target.kind) {
        case 'node':
            return {
                title: `Route captured → ${target.label}`,
                subtitle: 'evaluation continues; the last capture wins',
            };
        case 'no-capture':
        case 'unrouted':
            return {
                title: 'Continues without capturing a route',
                subtitle: 'evaluation continues to the next rule',
                warning: target.kind === 'unrouted' ? UNROUTED_WARNING : null,
            };
    }
}

function fallThroughContent(input: CdtDecisionTreeInput): Partial<CdtTreeBlock> {
    return targetContent(input.defaultNextNode, input.nodes, 'Ends the flow');
}

function targetContent(
    targetId: string | null,
    nodes: readonly CdtTreeNodeRef[],
    emptyTitle: string
): Partial<CdtTreeBlock> {
    if (!targetId) return { title: emptyTitle };
    return { title: `Continue to ${resolveNodeLabel(targetId, nodes)}` };
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function sortRows(rows: readonly ConditionGroup[]): ConditionGroup[] {
    // Same comparator as `payload.ts`, so diagram order equals persisted order.
    // Array.prototype.sort is stable, so rows without an `order` keep grid order.
    return [...rows].sort((a, b) => (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER));
}

function countRouteCodes(rows: readonly ConditionGroup[]): Map<string, number> {
    const counts = new Map<string, number>();
    for (const row of rows) {
        const code = row.route_code?.trim();
        if (code) counts.set(code, (counts.get(code) ?? 0) + 1);
    }
    return counts;
}

function indexCanvasRowsByRoute(rows: readonly ConditionGroup[]): Map<string, ConditionGroup> {
    const byRoute = new Map<string, ConditionGroup>();
    for (const row of rows) {
        const code = row.route_code?.trim();
        if (code && !byRoute.has(code)) byRoute.set(code, row);
    }
    return byRoute;
}

/** Rows sharing a route code share one port and one target — make that visible. */
function chipForSharedRoute(row: ConditionGroup, counts: Map<string, number>): string | null {
    const code = row.route_code?.trim();
    if (!code) return null;
    return (counts.get(code) ?? 0) > 1 ? `route ${code}` : null;
}

function codePreview(code: string): string {
    const lines = code
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => !!line)
        .slice(0, CDT_TREE_SUBTITLE_CODE_LINES);
    return clamp(lines.join(' '));
}

function clamp(text: string): string {
    const value = text?.trim() ?? '';
    return value.length > CDT_TREE_SUBTITLE_MAX_CHARS ? `${value.slice(0, CDT_TREE_SUBTITLE_MAX_CHARS - 1)}…` : value;
}

function sameParts(left: Record<string, string>, right: Record<string, string>): boolean {
    const leftKeys = Object.keys(left);
    const rightKeys = Object.keys(right);
    if (leftKeys.length !== rightKeys.length) return false;
    return leftKeys.every((key) => left[key] === right[key]);
}

/** Creates a block with defaults filled in, appends it, and returns its id. */
function block(sink: CdtTreeBlock[], partial: Partial<CdtTreeBlock> & { id: string; kind: CdtTreeBlockKind }): string {
    const title = partial.title ?? '';
    const subtitle = partial.subtitle ?? null;
    const detail = partial.detail ?? null;

    sink.push({
        id: partial.id,
        kind: partial.kind,
        title,
        subtitle,
        detail,
        // A clickable kind with nothing to show would open an empty popover, so
        // both have to hold — but only the kind decides the affordance.
        clickable: CLICKABLE_BY_KIND[partial.kind] && detail !== null,
        warning: partial.warning ?? null,
        chip: partial.chip ?? null,
        searchText: [title, subtitle, detail?.body]
            .filter((part) => !!part)
            .join(' ')
            .toLowerCase(),
    });

    return partial.id;
}

function edge(
    from: string,
    fromSide: CdtTreePortSide,
    to: string,
    toSide: CdtTreePortSide,
    kind: CdtTreeEdgeKind,
    label: string | null = null
): CdtTreeEdge {
    return { id: `${from}→${to}`, from, fromSide, to, toSide, kind, label };
}
