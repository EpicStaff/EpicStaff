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
import { CDT_TREE_COPY, CDT_TREE_SUBTITLE_MAX_CHARS, CLICKABLE_BY_KIND } from './cdt-decision-tree.constants';
import {
    CdtDecisionTreeInput,
    CdtTree,
    CdtTreeBlock,
    CdtTreeBlockKind,
    CdtTreeChainLane,
    CdtTreeDetail,
    CdtTreeEdge,
    CdtTreeEdgeKind,
    CdtTreeGroup,
    CdtTreeNodeRef,
    CdtTreePortSide,
    CdtTreeTarget,
} from './cdt-decision-tree.model';

export function buildCdtDecisionTree(input: CdtDecisionTreeInput): CdtTree {
    const blocks: CdtTreeBlock[] = [];
    const edges: CdtTreeEdge[] = [];

    const enabledRows = enabledRowsInOrder(input.rows);
    const hiddenRowCount = input.rows.length - enabledRows.length;
    const routeCodeCounts = countRouteCodes(enabledRows);

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
                // No preview: the two banded edges leave the shape narrower than it looks,
                // and the whole script is one click away in the detail window. Search
                // still reaches it through `detail.body`.
                subtitle: null,
                detail: { heading: CDT_TREE_COPY.detailPythonCode, language: 'python', body: preCode },
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
                // Title only, as with the computation steps: the pairs are a list, and
                // a list reads in the detail window, not squeezed onto one clipped
                // line. Search still reaches them through `detail.body`.
                subtitle: null,
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

    /** Last block before row evaluation. */
    const beforeRows = spineHead[spineHead.length - 1];

    // -- the exit row, created up front so rows can wire into it -------------
    //
    // Post-computation runs on the default exit and on a routed exit, and never on
    // an error: the engine sets `result_node` first and every error path returns
    // before that call. So the error column is a terminator on its own.

    const postCode = input.postCode?.trim() ?? '';
    const postComputation = (id: string): string | null =>
        postCode
            ? block(blocks, {
                  id,
                  kind: 'post-computation',
                  title: 'Post-computation',
                  // Same as pre-computation above: title only.
                  subtitle: null,
                  detail: { heading: CDT_TREE_COPY.detailPythonCode, language: 'python', body: postCode },
              })
            : null;

    const defaultPost = postComputation('exit:default:post');
    const defaultTerminator = block(blocks, {
        ...terminatorContent(input.defaultNextNode, input.nodes, CDT_TREE_COPY.endsFlow),
        id: 'exit:default:terminator',
        kind: 'exit-terminator',
    });
    const defaultEntry = defaultPost ?? defaultTerminator;
    if (defaultPost) {
        edges.push(edge(defaultPost, 'bottom', defaultTerminator, 'top', 'flow'));
    }

    const errorTerminator = block(blocks, {
        ...terminatorContent(input.errorNextNode, input.nodes, CDT_TREE_COPY.errorsEndFlow),
        id: 'exit:error:terminator',
        kind: 'exit-terminator',
    });

    // The route lane is only drawn when some rule actually leaves through it.
    // Built unconditionally it left a "Related node" — and, with a post-code, a
    // second copy of the post-computation — standing on the canvas with nothing
    // leading to them, on every table that routes nowhere.
    const rowTargets = resolveRowTargets(input);
    const anyRouted = rowTargets.some((target) => target.state === 'node');

    const routePost = anyRouted ? postComputation('exit:route:post') : null;
    const routeTerminator = anyRouted
        ? block(blocks, {
              id: 'exit:route:terminator',
              kind: 'exit-terminator',
              title: CDT_TREE_COPY.relatedNode,
          })
        : null;
    const routeEntry = routePost ?? routeTerminator;
    if (routePost && routeTerminator) {
        edges.push(edge(routePost, 'bottom', routeTerminator, 'top', 'flow'));
    }

    // -- the rules region ----------------------------------------------------
    //
    // It exists as a block because the `Error` edge leaves the whole region and
    // Foblex needs a real element to carry that connector. It is emitted after the
    // rules, so it also paints over them — harmless for the stroke, not harmless for
    // hit testing, which is why its host is `pointer-events: none` in the block.

    const region = enabledRows.length > 0 ? block(blocks, { id: 'rules:region', kind: 'rules-region' }) : null;

    // With rules, the error edge leaves the region as a whole. With none, the head
    // is still the pre-computation and the variable binding, and either can throw —
    // so the error exit has a source either way rather than standing unreachable.
    // It leaves the head sideways because the head's bottom already carries the
    // fall-through, and no block may have two edges leaving one side.
    edges.push(
        region
            ? edge(region, 'bottom', errorTerminator, 'top', 'error', 'Error')
            : edge(beforeRows, 'right', errorTerminator, 'top', 'error', 'Error')
    );

    // -- one branch per enabled row -----------------------------------------

    const chains: CdtTreeChainLane[] = [];

    enabledRows.forEach((row, index) => {
        const target = rowTargets[index];
        const routed = target.state === 'node';
        const continues = row.continue_flag ?? row.continue ?? false;
        const isLast = index + 1 >= enabledRows.length;

        const decision = block(blocks, {
            id: `row-${index}:decision`,
            kind: 'row-decision',
            title: row.group_name?.trim() || CDT_TREE_COPY.ruleFallback(index + 1),
            subtitle: rowExpressionSubtitle(row),
            detail: rowExpressionDetail(row),
            chip: chipForSharedRoute(row, routeCodeCounts),
            warning: rowWarning(row, target),
            target,
        });

        // `no` falls through to the next rule; after the last one the table default
        // applies, which is what the mockup labels `Default`.
        edges.push(
            isLast
                ? edge(decision, 'bottom', defaultEntry, 'top', 'default', 'Default')
                : edge(decision, 'bottom', `row-${index + 1}:decision`, 'top', 'no', 'no')
        );

        // The `yes` branch chains prompt → manipulation → route, in engine order.
        const chain: string[] = [];

        const prompt = row.prompt_id ? input.prompts?.[row.prompt_id] : undefined;
        if (row.prompt_id) {
            chain.push(
                block(blocks, {
                    id: `row-${index}:prompt`,
                    kind: 'row-prompt',
                    title: prompt ? row.prompt_id : CDT_TREE_COPY.promptLabel(row.prompt_id),
                    subtitle: prompt ? clamp(prompt.prompt_text) : null,
                    detail: prompt
                        ? {
                              heading: CDT_TREE_COPY.detailPrompt,
                              language: 'text',
                              body: promptDetailBody(prompt.prompt_text, prompt.result_variable),
                          }
                        : null,
                    warning: prompt ? null : CDT_TREE_COPY.promptMissingWarning,
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
                        heading: CDT_TREE_COPY.detailManipulation,
                        language: 'python',
                        body: toDisplayExpression(manipulation),
                    },
                })
            );
        }

        // Where the branch leaves, following the engine: an explicit route is
        // terminal whatever `continue` says; without one, `continue` rejoins the
        // next rule; anything else leaves `matched_next_node` unset, so the table
        // default applies.
        // `routeEntry` is non-null whenever any row is routed, so `routed` alone
        // decides; the check is what tells the compiler that.
        const exitTo =
            routed && routeEntry ? routeEntry : continues && !isLast ? `row-${index + 1}:decision` : defaultEntry;
        const exitKind: CdtTreeEdgeKind = !routed && continues && !isLast ? 'continue' : 'flow';

        if (chain.length > 0) {
            edges.push(edge(decision, 'right', chain[0], 'left', 'yes', 'yes'));
            for (let i = 1; i < chain.length; i++) {
                edges.push(edge(chain[i - 1], 'right', chain[i], 'left', 'flow'));
            }
            // Sideways, not down: leaving from the bottom sent the edge straight
            // through the branch below, which read as this rule handing over to
            // that one. Out to the right it drops through the clear strip past
            // every chain instead — see the layout's `corridorX`.
            edges.push(edge(chain[chain.length - 1], 'right', exitTo, 'top', exitKind));
        } else {
            // Neither a prompt nor a manipulation: the `yes` edge goes straight to
            // wherever the branch leaves.
            edges.push(edge(decision, 'right', exitTo, 'top', 'yes', 'yes'));
        }

        chains.push({ kind: 'chain', anchorId: decision, blockIds: chain });
    });

    if (enabledRows.length > 0) {
        edges.push(edge(beforeRows, 'bottom', 'row-0:decision', 'top', 'flow'));
    } else {
        // A table with no enabled rule still runs: nothing matches, so the table
        // default applies. Drawing nothing left the head and the exits as
        // disconnected boxes and hid a path the engine really takes.
        edges.push(edge(beforeRows, 'bottom', defaultEntry, 'top', 'default', CDT_TREE_COPY.noRowMatched));
    }

    assertUniqueEdgeIds(edges);

    // Reading order, which no other field carries: `blocks` is construction order
    // and puts the exits before the rules. Built from the same locals as the
    // lanes, so the list and the drawing cannot disagree about the rules.
    const exits = compact([defaultPost, defaultTerminator, errorTerminator, routePost, routeTerminator]);
    const groups: CdtTreeGroup[] = [
        { label: CDT_TREE_COPY.entryGroup, blockIds: spineHead },
        ...chains.map((chainEntry, index) => ({
            label: CDT_TREE_COPY.rowGroup(index + 1),
            blockIds: [chainEntry.anchorId, ...chainEntry.blockIds],
        })),
        { label: CDT_TREE_COPY.exitGroup, blockIds: exits },
    ];

    return {
        title: input.nodeName,
        blocks,
        edges,
        groups,
        lanes: [
            { kind: 'spine', blockIds: [...spineHead, ...chains.map((chainEntry) => chainEntry.anchorId)] },
            ...chains,
            ...(region
                ? [
                      {
                          kind: 'region' as const,
                          blockId: region,
                          coversIds: chains.flatMap((chainEntry) => [chainEntry.anchorId, ...chainEntry.blockIds]),
                      },
                  ]
                : []),
            {
                kind: 'exits',
                columns: [
                    { blockIds: compact([defaultPost, defaultTerminator]), anchor: 'spine' },
                    { blockIds: [errorTerminator], anchor: 'region' },
                    ...(routeEntry
                        ? [
                              {
                                  blockIds: compact([routePost, routeTerminator]),
                                  anchor: 'chain-corridor' as const,
                              },
                          ]
                        : []),
                ],
            },
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
    return combined ? clamp(toDisplayExpression(combined)) : CDT_TREE_COPY.alwaysMatches;
}

function rowExpressionDetail(row: ConditionGroup): CdtTreeDetail | null {
    const combined = combinedExpression(row);
    if (!combined) return null;
    return { heading: CDT_TREE_COPY.detailExpression, language: 'python', body: toDisplayExpression(combined) };
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
): CdtTreeTarget {
    const code = row.route_code?.trim();
    if (!code) return { state: 'unrouted' };

    let targetId = canvasRowsByRoute.get(code)?.next_node ?? row.next_node ?? null;

    if (!targetId) {
        const portId = `${input.nodeId}_decision-route-${slugifyRouteCode(code)}`;
        targetId =
            input.connections.find(
                (connection) => connection.sourceNodeId === input.nodeId && connection.sourcePortId === portId
            )?.targetNodeId ?? null;
    }

    return targetId ? { state: 'node', label: resolveNodeLabel(targetId, input.nodes) } : { state: 'no-capture' };
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

/**
 * A terminator takes the name of the node attached to that output, so the diagram
 * reads as "and then this node runs". With nothing attached the graph really does
 * end there, which is what the fallback says.
 */
function terminatorContent(
    targetId: string | null,
    nodes: readonly CdtTreeNodeRef[],
    emptyTitle: string
): Partial<CdtTreeBlock> {
    if (!targetId) return { target: { state: 'end' }, title: emptyTitle };

    const label = resolveNodeLabel(targetId, nodes);
    return { target: { state: 'node', label }, title: label };
}

/**
 * What is off about a rule, if anything — one line, because a block shows one
 * badge, ordered by how much misreading it costs.
 *
 * A rule with a target but no route code loses that target on save: `payload.ts`
 * only persists one when a route code is present. A rule with neither is an
 * enrichment step that falls through by design and gets no badge.
 *
 * A rule that both routes and continues is the one that reads as broken tooling.
 * The engine checks `next_node` first and breaks, so `continue_flag` is never
 * read — the tick does nothing, and without a badge the diagram simply ignores
 * it in silence.
 */
function rowWarning(row: ConditionGroup, target: CdtTreeTarget): string | null {
    const routed = !!row.route_code?.trim();
    if (!routed && !!row.next_node) return CDT_TREE_COPY.unsavedTargetWarning;

    const continues = row.continue_flag ?? row.continue ?? false;
    // `target.state === 'node'` rather than the mere presence of a route code:
    // the engine breaks on a resolved target, and a route that resolves to
    // nothing does let `continue` through.
    return target.state === 'node' && continues ? CDT_TREE_COPY.routedContinueWarning : null;
}

function compact(ids: readonly (string | null)[]): string[] {
    return ids.filter((id): id is string => id !== null);
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

/**
 * The rows the diagram draws, in evaluation order.
 *
 * Exported because `row-<i>:*` block ids index into this list: anything that maps
 * an id back to its rule — the explain payload does — has to apply the same filter
 * and the same sort, and one shared function is the only way to be sure it does.
 */
export function enabledRowsInOrder(rows: readonly ConditionGroup[]): ConditionGroup[] {
    return sortRowsByOrder(rows.filter((row) => row.dock_visible !== false));
}

/** Each drawn row's routing target, aligned index-for-index with `enabledRowsInOrder`. */
export function resolveRowTargets(input: CdtDecisionTreeInput): CdtTreeTarget[] {
    const canvasRowsByRoute = indexCanvasRowsByRoute(input.canvasRows);
    return enabledRowsInOrder(input.rows).map((row) => resolveRowTarget(row, input, canvasRowsByRoute));
}

export function sortRowsByOrder(rows: readonly ConditionGroup[]): ConditionGroup[] {
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
    return (counts.get(code) ?? 0) > 1 ? CDT_TREE_COPY.sharedRouteChip(code) : null;
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
        // A clickable kind with nothing to show would open an empty window, so
        // both have to hold — but only the kind decides the affordance.
        clickable: CLICKABLE_BY_KIND[partial.kind] && detail !== null,
        target: partial.target ?? null,
        warning: partial.warning ?? null,
        chip: partial.chip ?? null,
        searchText: [title, subtitle, detail?.body]
            .filter((part) => !!part)
            .join(' ')
            .toLowerCase(),
    });

    return partial.id;
}

/**
 * The id carries `kind` because a pair of blocks can be joined twice.
 *
 * A rule with neither a prompt nor a manipulation does nothing, so its `yes`
 * branch leaves for the same block its fall-through does — two edges, one pair of
 * endpoints. Keyed on the pair alone they came out with the same id, and since
 * the connector ids are derived from it (see `outputConnectorId`) so did their
 * connectors. Foblex's store throws on a duplicate id, which aborts registration
 * for that edge *and every one declared after it*: the diagram quietly lost its
 * whole tail, most visibly the edge into the first rule, which is declared last.
 */
function edge(
    from: string,
    fromSide: CdtTreePortSide,
    to: string,
    toSide: CdtTreePortSide,
    kind: CdtTreeEdgeKind,
    label: string | null = null
): CdtTreeEdge {
    return { id: `${kind}:${from}→${to}`, from, fromSide, to, toSide, kind, label };
}

/**
 * Fail here, naming the id, rather than three frames away inside Foblex — where
 * the same mistake costs the tail of the diagram and logs nothing that points
 * back at this file. `kind` is what keeps ids apart today; this is what catches
 * the next arrangement for which that is no longer enough.
 */
function assertUniqueEdgeIds(edges: readonly CdtTreeEdge[]): void {
    const seen = new Set<string>();

    for (const entry of edges) {
        if (seen.has(entry.id)) throw new Error(`cdt-decision-tree: two edges share the id "${entry.id}"`);
        seen.add(entry.id);
    }
}
