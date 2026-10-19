import { NodeType } from '@shared/models';

import { FlowModel } from '../../core/models/flow.model';
import { ClassificationDecisionTableNodeModel, DecisionTableNodeModel } from '../../core/models/node.model';
import { EdgeDiffEntry, EdgeRouteKind } from './types';

/** An edge described by match keys and a semantic port, so it is the same on every load. */
export interface SemanticEdge {
    key: string;
    sourceKey: string;
    targetKey: string;
    routeKind: EdgeRouteKind;
    route: string | null;
}

/**
 * The edges of one side, keyed by node match keys:
 * - plain edges from the canvas connections whose source is not a decision table;
 * - decision-table routes from the table data (the source of truth the save path uses), keyed by
 *   group name / `default` / `error`, never by canvas port ids (they are regenerated).
 * A reference to a node that is not on this side is skipped, as the loaders do.
 */
export function collectSemanticEdges(flow: FlowModel, keyById: ReadonlyMap<string, string>): SemanticEdge[] {
    const edgesByKey = new Map<string, SemanticEdge>();
    const add = (edge: Omit<SemanticEdge, 'key'>): void => {
        const key =
            edge.route === null
                ? `${edge.routeKind}:${edge.sourceKey}->${edge.targetKey}`
                : `${edge.routeKind}:${edge.sourceKey}:${edge.route}->${edge.targetKey}`;
        if (!edgesByKey.has(key)) edgesByKey.set(key, { key, ...edge });
    };

    const typeById = new Map(flow.nodes.map((node) => [node.id, node.type]));
    for (const connection of flow.connections) {
        const sourceType = typeById.get(connection.sourceNodeId);
        if (sourceType === NodeType.TABLE || sourceType === NodeType.CLASSIFICATION_TABLE) continue;
        const sourceKey = keyById.get(connection.sourceNodeId);
        const targetKey = keyById.get(connection.targetNodeId);
        if (!sourceKey || !targetKey) continue;
        add({ sourceKey, targetKey, routeKind: 'edge', route: null });
    }

    for (const node of flow.nodes) {
        const sourceKey = keyById.get(node.id);
        if (!sourceKey) continue;
        const routes =
            node.type === NodeType.TABLE
                ? decisionTableRoutes(node)
                : node.type === NodeType.CLASSIFICATION_TABLE
                  ? classificationTableRoutes(node)
                  : [];
        const routeKind: EdgeRouteKind = node.type === NodeType.TABLE ? 'dt-route' : 'cdt-route';
        for (const { route, target } of routes) {
            const targetKey = target ? keyById.get(target) : undefined;
            if (targetKey) add({ sourceKey, targetKey, routeKind, route });
        }
    }

    return [...edgesByKey.values()];
}

/**
 * What a restore does to the edges: an edge on both sides is unchanged, a version-only edge is added,
 * a canvas-only edge is deleted. Version edges come first (in version order), then the canvas-only ones.
 */
export function diffEdges(
    currentEdges: readonly SemanticEdge[],
    versionEdges: readonly SemanticEdge[]
): EdgeDiffEntry[] {
    const currentKeys = new Set(currentEdges.map((edge) => edge.key));
    const versionKeys = new Set(versionEdges.map((edge) => edge.key));
    return [
        ...versionEdges.map((edge) => ({
            ...edge,
            status: currentKeys.has(edge.key) ? ('unchanged' as const) : ('added' as const),
        })),
        ...currentEdges
            .filter((edge) => !versionKeys.has(edge.key))
            .map((edge) => ({ ...edge, status: 'deleted' as const })),
    ];
}

interface Route {
    route: string;
    target: string | null | undefined;
}

/** Invalid groups are never saved, so they route nowhere. */
function decisionTableRoutes(node: DecisionTableNodeModel): Route[] {
    const table = node.data.table;
    return [
        ...(table.condition_groups ?? [])
            .filter((group) => group.valid !== false)
            .map((group) => ({ route: `group:${group.group_name}`, target: group.next_node })),
        { route: 'default', target: table.default_next_node },
        { route: 'error', target: table.next_error_node },
    ];
}

/** A group without a route code has no output port, so it draws no edge (same as the loader). */
function classificationTableRoutes(node: ClassificationDecisionTableNodeModel): Route[] {
    const table = node.data.table;
    return [
        ...(table.condition_groups ?? [])
            .filter((group) => !!group.route_code)
            .map((group) => ({ route: `group:${group.group_name}`, target: group.next_node })),
        { route: 'default', target: table.default_next_node },
        { route: 'error', target: table.next_error_node },
    ];
}
