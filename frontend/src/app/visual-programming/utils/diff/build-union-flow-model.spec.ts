import { NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { convertDecisionTableToCdt } from '../../core/helpers/dt-to-cdt-converter';
import { Edge } from '../../core/models/edge.model';
import { FlowModel } from '../../core/models/flow.model';
import { DecisionTableNodeModel, NodeModel } from '../../core/models/node.model';
import { buildFlowModelFromGraphDto } from '../load';
import {
    LIVE_NODE_ID as ID,
    LIVE_NODE_UUID as UUID,
    liveAgent,
    liveClassificationTable,
    liveDecisionTable,
    liveEnd,
    liveGraph,
    liveNote,
    livePython,
    liveStart,
    liveTask,
} from '../testing/live-graph.fixture';
import { buildFlowDiff } from './build-flow-diff';
import { buildUnionFlowModel, UnionFlowModel } from './build-union-flow-model';
import { MissingReference } from './types';

// Both sides are loaded from graph rows, like the live canvas and the preview: each load gives new canvas
// ids, and the node uuids pair the nodes up.

const NO_NODE_LISTS = Object.fromEntries(
    Object.keys(liveGraph)
        .filter((key) => key.endsWith('_list'))
        .map((key) => [key, []])
);

/** A row's canvas position (and size), as the canvas stores them in node metadata. */
function at(x: number, y: number, size?: { width: number; height: number }) {
    return { metadata: { position: { x, y }, ...(size ? { size } : {}) } };
}

// Far from everything else, so it never takes part in placement.
const START = { ...liveStart, ...at(-3000, -3000) };

function load(rows: Partial<GraphDto>): FlowModel {
    return buildFlowModelFromGraphDto({
        ...liveGraph,
        ...NO_NODE_LISTS,
        start_node_list: [START],
        ...rows,
    } as GraphDto);
}

function edge(id: number, from: number, to: number): Edge {
    return { id, graph: 1, start_node_id: from, end_node_id: to, metadata: {} };
}

function unionOf(
    versionFlow: FlowModel,
    liveFlow: FlowModel,
    versionWarningReferences: ReadonlyMap<string, readonly MissingReference[]> = new Map()
): UnionFlowModel {
    return buildUnionFlowModel(
        buildFlowDiff({ versionFlow, liveFlow, versionWarningReferences, versionKeyValueTableNames: new Map() })
    );
}

function nodeOf(model: UnionFlowModel, nodeUuid: string): NodeModel {
    return model.flow.nodes.find((node) => node.nodeUuid === nodeUuid)!;
}

function nameOf(model: UnionFlowModel, nodeId: string): string {
    return model.flow.nodes.find((node) => node.id === nodeId)!.node_name;
}

/** Real node rectangles (no placement margin). */
function overlaps(first: NodeModel, second: NodeModel): boolean {
    return (
        first.position.x < second.position.x + second.size.width &&
        second.position.x < first.position.x + first.size.width &&
        first.position.y < second.position.y + second.size.height &&
        second.position.y < first.position.y + first.size.height
    );
}

describe('buildUnionFlowModel', () => {
    describe('positions', () => {
        it('shows every version node at its version position, and a canvas-only node where it is when that spot is free', () => {
            const version = load({
                python_node_list: [{ ...livePython, ...at(0, 0) }],
                task_node_list: [{ ...liveTask, ...at(0, 300) }],
            });
            const live = load({
                python_node_list: [{ ...livePython, ...at(800, 800) }],
                end_node_list: [{ ...liveEnd, ...at(1200, 0) }],
            });

            const model = unionOf(version, live);

            expect(nodeOf(model, UUID.python).position).toEqual({ x: 0, y: 0 });
            expect(nodeOf(model, UUID.task).position).toEqual({ x: 0, y: 300 });
            expect(nodeOf(model, UUID.end).position).toEqual({ x: 1200, y: 0 });
        });

        it('moves a canvas-only node to the nearest free grid spot, clear of version nodes and of the nodes moved before it', () => {
            const version = load({ python_node_list: [{ ...livePython, ...at(0, 0) }] });
            const live = load({
                python_node_list: [{ ...livePython, ...at(0, 0) }],
                end_node_list: [{ ...liveEnd, ...at(0, 0) }],
                graph_note_list: [{ ...liveNote, ...at(0, 0) }],
            });

            const model = unionOf(version, live);

            expect(nodeOf(model, UUID.python).position).toEqual({ x: 0, y: 0 });
            // The note is placed first (canvas order): five grid cells up clears the Python node. The End
            // node then finds that spot taken and goes five cells down.
            expect(nodeOf(model, UUID.note).position).toEqual({ x: 0, y: -100 });
            expect(nodeOf(model, UUID.end).position).toEqual({ x: 0, y: 100 });
        });

        it('never moves a version node, even one that covers another version node', () => {
            const version = load({
                python_node_list: [{ ...livePython, ...at(0, 0) }],
                task_node_list: [{ ...liveTask, ...at(0, 0) }],
            });

            const model = unionOf(version, load({}));

            expect(nodeOf(model, UUID.python).position).toEqual({ x: 0, y: 0 });
            expect(nodeOf(model, UUID.task).position).toEqual({ x: 0, y: 0 });
        });

        it('moves a version node off a table only when the rows of the routes a restore removes make the table cover it', () => {
            // The table is 240 high in the version; one more route on the canvas adds a 60 high row.
            const rows = {
                python_node_list: [{ ...livePython, ...at(0, 280) }],
                task_node_list: [{ ...liveTask, ...at(0, 100) }],
                end_node_list: [{ ...liveEnd, ...at(2000, 0) }],
            };
            const extraRoute = {
                ...liveDecisionTable.condition_groups[0],
                id: 9,
                group_name: 'extra',
                order: 2,
            };
            const version = load({ ...rows, decision_table_node_list: [{ ...liveDecisionTable, ...at(0, 0) }] });
            const live = load({
                ...rows,
                decision_table_node_list: [
                    {
                        ...liveDecisionTable,
                        ...at(0, 0),
                        condition_groups: [...liveDecisionTable.condition_groups, extraRoute],
                    },
                ],
            });

            const model = unionOf(version, live);

            expect(nodeOf(model, UUID.decisionTable).position).toEqual({ x: 0, y: 0 });
            // Clear below the grown table.
            expect(nodeOf(model, UUID.python).position).toEqual({ x: 0, y: 340 });
            // It overlapped the table in the version already: not the extra rows' doing, so it stays.
            expect(nodeOf(model, UUID.task).position).toEqual({ x: 0, y: 100 });
        });

        describe('a classification table whose version has groups without a route code', () => {
            // Such a group has a port (keyed by its name) but no row, on both canvases.
            const routeA = liveClassificationTable.condition_groups[0];
            const noRouteCode = (id: number, name: string) => ({ ...routeA, id, group_name: name, route_code: null });
            const route = (id: number, code: string) => ({ ...routeA, id, group_name: code, route_code: code });
            const versionTable = {
                ...liveClassificationTable,
                ...at(0, 0),
                condition_groups: [routeA, noRouteCode(20, 'Condition 5'), noRouteCode(21, 'Condition 4')],
            };
            const python = { ...livePython, ...at(0, 300) };

            it('grows by the routes only the canvas has, not by its own rowless groups, and moves the node below off it', () => {
                const liveTable = {
                    ...liveClassificationTable,
                    ...at(0, 0),
                    condition_groups: [routeA, route(30, 'R1'), route(31, 'R2'), route(32, 'R3')],
                };

                const model = unionOf(
                    load({ python_node_list: [python], classification_decision_table_node_list: [versionTable] }),
                    load({ python_node_list: [python], classification_decision_table_node_list: [liveTable] })
                );

                const table = nodeOf(model, UUID.classificationTable);
                expect([...model.diffState.currentOnlyRoutePortIds].sort()).toEqual([
                    `${table.id}_decision-route-r1`,
                    `${table.id}_decision-route-r2`,
                    `${table.id}_decision-route-r3`,
                ]);
                // Header, route A, three removed routes, Default, Error: 7 rows of 60.
                expect(table.size.height).toBe(420);
                expect(overlaps(nodeOf(model, UUID.python), table)).toBe(false);
            });

            it('does not grow or move anything when the canvas has no route of its own', () => {
                const model = unionOf(
                    load({ python_node_list: [python], classification_decision_table_node_list: [versionTable] }),
                    load({
                        python_node_list: [python],
                        classification_decision_table_node_list: [{ ...liveClassificationTable, ...at(0, 0) }],
                    })
                );

                const table = nodeOf(model, UUID.classificationTable);
                expect(model.diffState.currentOnlyRoutePortIds.size).toBe(0);
                expect(table.size.height).toBe(240);
                expect(nodeOf(model, UUID.python).position).toEqual({ x: 0, y: 300 });
            });
        });

        it('does not grow by a group of the canvas without a route code, which the canvas shows no row for', () => {
            const routeA = liveClassificationTable.condition_groups[0];
            const python = { ...livePython, ...at(0, 300) };
            const liveTable = {
                ...liveClassificationTable,
                ...at(0, 0),
                condition_groups: [routeA, { ...routeA, id: 22, group_name: 'Fresh group', route_code: null }],
            };

            const model = unionOf(
                load({
                    python_node_list: [python],
                    classification_decision_table_node_list: [{ ...liveClassificationTable, ...at(0, 0) }],
                }),
                load({ python_node_list: [python], classification_decision_table_node_list: [liveTable] })
            );

            expect(model.diffState.currentOnlyRoutePortIds.size).toBe(0);
            expect(nodeOf(model, UUID.classificationTable).size.height).toBe(240);
            expect(nodeOf(model, UUID.python).position).toEqual({ x: 0, y: 300 });
        });

        it('moves a node under one grown table clear of a second grown table too', () => {
            const decisionExtra = { ...liveDecisionTable.condition_groups[0], id: 9, group_name: 'extra', order: 2 };
            const routeA = liveClassificationTable.condition_groups[0];
            const classificationExtras = ['R1', 'R2', 'R3'].map((code, index) => ({
                ...routeA,
                id: 40 + index,
                group_name: code,
                route_code: code,
            }));
            const python = { ...livePython, ...at(0, 280) };
            const classificationAt = at(0, 400);
            const version = load({
                python_node_list: [python],
                decision_table_node_list: [{ ...liveDecisionTable, ...at(0, 0) }],
                classification_decision_table_node_list: [{ ...liveClassificationTable, ...classificationAt }],
            });
            const live = load({
                python_node_list: [python],
                decision_table_node_list: [
                    {
                        ...liveDecisionTable,
                        ...at(0, 0),
                        condition_groups: [...liveDecisionTable.condition_groups, decisionExtra],
                    },
                ],
                classification_decision_table_node_list: [
                    {
                        ...liveClassificationTable,
                        ...classificationAt,
                        condition_groups: [routeA, ...classificationExtras],
                    },
                ],
            });

            const model = unionOf(version, live);

            const moved = nodeOf(model, UUID.python);
            expect(moved.position).not.toEqual({ x: 0, y: 280 });
            expect(overlaps(moved, nodeOf(model, UUID.decisionTable))).toBe(false);
            expect(overlaps(moved, nodeOf(model, UUID.classificationTable))).toBe(false);
            expect(nodeOf(model, UUID.classificationTable).position).toEqual({ x: 0, y: 400 });
        });

        it('keeps a canvas-only node where it is when no free spot is within the search radius', () => {
            const version = load({
                graph_note_list: [{ ...liveNote, ...at(-2000, -2000, { width: 4000, height: 4000 }) }],
            });
            const live = load({ python_node_list: [{ ...livePython, ...at(0, 0) }] });

            const model = unionOf(version, live);

            expect(nodeOf(model, UUID.python).position).toEqual({ x: 0, y: 0 });
        });

        it('puts a converted table (version decision table, canvas classification table) next to each other', () => {
            const version = load({ decision_table_node_list: [{ ...liveDecisionTable, ...at(400, 0) }] });
            const versionTable = version.nodes.find((node) => node.type === NodeType.TABLE) as DecisionTableNodeModel;
            const { node: convertedTable } = convertDecisionTableToCdt(versionTable);
            const live: FlowModel = {
                nodes: [...load({}).nodes, convertedTable],
                connections: [],
            };

            const model = unionOf(version, live);
            const decisionTable = model.flow.nodes.find((node) => node.type === NodeType.TABLE)!;
            const classificationTable = model.flow.nodes.find((node) => node.type === NodeType.CLASSIFICATION_TABLE)!;

            expect(model.diffState.nodes.get(decisionTable.id)?.status).toBe('added');
            expect(model.diffState.nodes.get(classificationTable.id)?.status).toBe('deleted');
            expect(decisionTable.position).toEqual({ x: 400, y: 0 });
            expect(overlaps(decisionTable, classificationTable)).toBe(false);
        });
    });

    describe('ports', () => {
        // The version has one route; the canvas has one more, to the Task node: a restore removes it.
        const cases = [
            {
                table: 'decision table',
                versionRows: { decision_table_node_list: [liveDecisionTable] },
                liveRows: {
                    decision_table_node_list: [
                        {
                            ...liveDecisionTable,
                            condition_groups: [
                                ...liveDecisionTable.condition_groups,
                                {
                                    ...liveDecisionTable.condition_groups[0],
                                    id: 9,
                                    group_name: 'Not Yet',
                                    next_node_id: ID.task,
                                    order: 2,
                                },
                            ],
                        },
                    ],
                },
                removedRoutePort: 'decision-out-not-yet',
            },
            {
                table: 'classification table',
                versionRows: { classification_decision_table_node_list: [liveClassificationTable] },
                liveRows: {
                    classification_decision_table_node_list: [
                        {
                            ...liveClassificationTable,
                            condition_groups: [
                                ...liveClassificationTable.condition_groups,
                                {
                                    ...liveClassificationTable.condition_groups[0],
                                    id: 9,
                                    group_name: 'other',
                                    route_code: 'Route B',
                                    next_node_id: ID.task,
                                    order: 2,
                                },
                            ],
                        },
                    ],
                },
                removedRoutePort: 'decision-route-route-b',
            },
        ];

        it.each(cases)(
            'gives a $table on both sides the routes of both, so the route a restore removes still attaches',
            ({ versionRows, liveRows, removedRoutePort }) => {
                const targets = {
                    end_node_list: [liveEnd],
                    task_node_list: [liveTask],
                    agent_node_list: [liveAgent],
                };
                const model = unionOf(load({ ...targets, ...versionRows }), load({ ...targets, ...liveRows }));

                const table = model.flow.nodes.find(
                    (node) => node.type === NodeType.TABLE || node.type === NodeType.CLASSIFICATION_TABLE
                )!;
                const removedRoute = model.flow.connections.find(
                    (connection) => connection.sourcePortId === `${table.id}_${removedRoutePort}`
                );
                expect(removedRoute).toBeDefined();
                // Without the port, the canvas would silently drop the edge.
                expect(table.ports?.map((port) => port.id)).toContain(removedRoute!.sourcePortId);
                expect(nameOf(model, removedRoute!.targetNodeId)).toBe('Task');
                expect(model.diffState.connections.get(removedRoute!.id)).toBe('deleted');
                // The table still shows the version: the extra port does not add the group to its data.
                expect(model.diffState.nodes.get(table.id)?.status).toBe('changed');
            }
        );

        it.each(cases)(
            'marks the route only the version of a $table has as one a restore adds, and no other port',
            ({ versionRows, liveRows, removedRoutePort: extraRoutePort }) => {
                const targets = {
                    end_node_list: [liveEnd],
                    task_node_list: [liveTask],
                    agent_node_list: [liveAgent],
                };
                // The sides swapped: now the version has the extra route.
                const model = unionOf(load({ ...targets, ...liveRows }), load({ ...targets, ...versionRows }));
                const swappedBack = unionOf(load({ ...targets, ...versionRows }), load({ ...targets, ...liveRows }));

                const table = model.flow.nodes.find(
                    (node) => node.type === NodeType.TABLE || node.type === NodeType.CLASSIFICATION_TABLE
                )!;
                expect([...model.diffState.versionOnlyPortIds]).toEqual([`${table.id}_${extraRoutePort}`]);
                expect([...swappedBack.diffState.versionOnlyPortIds]).toEqual([]);
            }
        );

        it.each(cases)(
            'lists the route only the canvas side of a $table has as one a restore removes, and no other port',
            ({ versionRows, liveRows, removedRoutePort }) => {
                const targets = {
                    end_node_list: [liveEnd],
                    task_node_list: [liveTask],
                    agent_node_list: [liveAgent],
                };
                const model = unionOf(load({ ...targets, ...versionRows }), load({ ...targets, ...liveRows }));
                const swapped = unionOf(load({ ...targets, ...liveRows }), load({ ...targets, ...versionRows }));

                const table = model.flow.nodes.find(
                    (node) => node.type === NodeType.TABLE || node.type === NodeType.CLASSIFICATION_TABLE
                )!;
                expect([...model.diffState.currentOnlyRoutePortIds]).toEqual([`${table.id}_${removedRoutePort}`]);
                expect([...swapped.diffState.currentOnlyRoutePortIds]).toEqual([]);
            }
        );

        it('marks no port of a table only the version has: the node itself is added', () => {
            const model = unionOf(load({ decision_table_node_list: [liveDecisionTable] }), load({}));

            expect(model.diffState.versionOnlyPortIds.size).toBe(0);
        });

        it('marks no classification route the canvas also has, even when the version adds a group to it', () => {
            const routeA = liveClassificationTable.condition_groups[0];
            const versionTable = {
                ...liveClassificationTable,
                condition_groups: [routeA, { ...routeA, id: 9, group_name: 'new group, same route', order: 2 }],
            };
            const model = unionOf(
                load({ agent_node_list: [liveAgent], classification_decision_table_node_list: [versionTable] }),
                load({
                    agent_node_list: [liveAgent],
                    classification_decision_table_node_list: [liveClassificationTable],
                })
            );

            expect(model.diffState.versionOnlyPortIds.size).toBe(0);
        });

        it('draws a line that two routes share once, unchanged while one of them stays', () => {
            // Two groups with one route code and one target leave through one port: one line on the canvas.
            const routeToAgent = liveClassificationTable.condition_groups[0];
            const twoRoutesToAgent = {
                ...liveClassificationTable,
                condition_groups: [routeToAgent, { ...routeToAgent, id: 9, group_name: 'same route', order: 2 }],
            };
            const model = unionOf(
                load({
                    agent_node_list: [liveAgent],
                    classification_decision_table_node_list: [liveClassificationTable],
                }),
                load({ agent_node_list: [liveAgent], classification_decision_table_node_list: [twoRoutesToAgent] })
            );

            const linesToAgent = model.flow.connections.filter(
                (connection) => nameOf(model, connection.targetNodeId) === 'Agent'
            );
            expect(linesToAgent.map((connection) => model.diffState.connections.get(connection.id))).toEqual([
                'unchanged',
            ]);
        });

        it('gives every edge a source and a target port that its nodes have', () => {
            const version = load({
                python_node_list: [livePython],
                decision_table_node_list: [liveDecisionTable],
                classification_decision_table_node_list: [liveClassificationTable],
                end_node_list: [liveEnd],
                task_node_list: [liveTask],
                agent_node_list: [liveAgent],
                edge_list: [edge(1, ID.start, ID.python), edge(2, ID.python, ID.decisionTable)],
            });
            const live = load({
                python_node_list: [livePython],
                decision_table_node_list: [{ ...liveDecisionTable, default_next_node_id: ID.end }],
                end_node_list: [liveEnd],
                task_node_list: [liveTask],
                edge_list: [edge(1, ID.start, ID.python), edge(3, ID.task, ID.end)],
            });

            const model = unionOf(version, live);
            const portIds = new Set(model.flow.nodes.flatMap((node) => (node.ports ?? []).map((port) => port.id)));

            expect(model.flow.connections.length).toBeGreaterThan(0);
            for (const connection of model.flow.connections) {
                expect(portIds).toContain(connection.sourcePortId);
                expect(portIds).toContain(connection.targetPortId);
            }
        });
    });

    describe('statuses and edges', () => {
        // Version: Start → Python → Task (renamed), plus an Agent. Canvas: Start → Python → End, and Task.
        const version = load({
            python_node_list: [livePython],
            task_node_list: [{ ...liveTask, node_name: 'Task v2' }],
            agent_node_list: [{ ...liveAgent, ...at(0, 600) }],
            edge_list: [edge(1, ID.start, ID.python), edge(2, ID.python, ID.task)],
        });
        const live = load({
            python_node_list: [livePython],
            task_node_list: [liveTask],
            end_node_list: [{ ...liveEnd, ...at(900, 0) }],
            edge_list: [edge(1, ID.start, ID.python), edge(3, ID.python, ID.end)],
        });
        const versionPythonId = version.nodes.find((node) => node.nodeUuid === UUID.python)!.id;
        const missingAgent: MissingReference = {
            path: 'agent_definition',
            field: 'agent_definition',
            missing: 41,
            source: 'warning',
        };

        it('marks each node with what a restore does to it; a missing reference leaves its status alone', () => {
            const model = unionOf(version, live, new Map([[versionPythonId, [missingAgent]]]));

            const statuses = Object.fromEntries(
                model.flow.nodes.map((node) => [node.node_name, model.diffState.nodes.get(node.id)?.status])
            );
            expect(statuses).toEqual({
                __start__: 'unchanged',
                Python: 'unchanged',
                'Task v2': 'changed',
                Agent: 'added',
                __end_node__: 'deleted',
            });
        });

        it('keeps the field changes and missing references of each node for its panel', () => {
            const model = unionOf(version, live, new Map([[versionPythonId, [missingAgent]]]));
            const stateOf = (name: string) =>
                model.diffState.nodes.get(model.flow.nodes.find((node) => node.node_name === name)!.id)!;

            expect(stateOf('Task v2').fields).toEqual([
                { path: 'node_name', field: 'node_name', status: 'changed', current: 'Task', version: 'Task v2' },
            ]);
            expect(stateOf('Python')).toMatchObject({ fields: [], missingReferences: [missingAgent] });
            expect(stateOf('Task v2').missingReferences).toEqual([]);
        });

        it('keeps the canvas side of a node for its panel, none for a node only the version has', () => {
            const model = unionOf(version, live);
            const stateOf = (name: string) =>
                model.diffState.nodes.get(model.flow.nodes.find((node) => node.node_name === name)!.id)!;

            expect(stateOf('Task v2').currentNode?.node_name).toBe('Task');
            expect(stateOf('Agent').currentNode).toBeUndefined();
        });

        it('gives a node only on the canvas neither field changes nor missing references', () => {
            const model = unionOf(version, live, new Map([[versionPythonId, [missingAgent]]]));

            const end = model.diffState.nodes.get(model.flow.nodes.find((node) => node.type === NodeType.END)!.id);
            expect(end).toMatchObject({ status: 'deleted', fields: [], missingReferences: [] });
        });

        it('draws every edge of both sides once, between the union nodes, with its status', () => {
            const model = unionOf(version, live);

            const edges = model.flow.connections.map((connection) => [
                `${nameOf(model, connection.sourceNodeId)} -> ${nameOf(model, connection.targetNodeId)}`,
                model.diffState.connections.get(connection.id),
            ]);
            expect(edges).toEqual([
                ['__start__ -> Python', 'unchanged'],
                ['Python -> Task v2', 'added'],
                ['Python -> __end_node__', 'deleted'],
            ]);
        });

        it('gives every node a new canvas id and maps the version ids to them', () => {
            const model = unionOf(version, live);

            const sideIds = new Set([...version.nodes, ...live.nodes].map((node) => node.id));
            const unionIds = model.flow.nodes.map((node) => node.id);
            expect(unionIds.filter((id) => sideIds.has(id))).toEqual([]);
            expect(new Set(unionIds).size).toBe(unionIds.length);
            for (const versionNode of version.nodes) {
                const unionId = model.unionIdByVersionId.get(versionNode.id);
                expect(model.flow.nodes.find((node) => node.id === unionId)?.nodeUuid).toBe(versionNode.nodeUuid);
            }
        });

        it('finds the union node a route of a field change names, on both sides and on the canvas only', () => {
            const model = unionOf(
                load({
                    decision_table_node_list: [liveDecisionTable],
                    task_node_list: [liveTask],
                    end_node_list: [liveEnd],
                }),
                load({
                    decision_table_node_list: [{ ...liveDecisionTable, default_next_node_id: ID.python }],
                    python_node_list: [{ ...livePython, uuid: 'canvas-only-python' }],
                    task_node_list: [liveTask],
                    end_node_list: [liveEnd],
                })
            );
            const table = nodeOf(model, UUID.decisionTable);
            const route = model.diffState.nodes
                .get(table.id)!
                .fields.find((change) => change.field === 'default_next_node')!;

            expect(nameOf(model, model.diffState.nodeIdByKey.get(route.current as string)!)).toBe('Python');
            expect(nameOf(model, model.diffState.nodeIdByKey.get(route.version as string)!)).toBe('Task');
        });

        it('points the routes of a table at the union nodes', () => {
            const model = unionOf(
                load({
                    decision_table_node_list: [liveDecisionTable],
                    task_node_list: [liveTask],
                    end_node_list: [liveEnd],
                }),
                load({ task_node_list: [liveTask], end_node_list: [liveEnd] })
            );

            const table = nodeOf(model, UUID.decisionTable) as DecisionTableNodeModel;
            expect(table.data.table.default_next_node).toBe(nodeOf(model, UUID.task).id);
            expect(table.data.table.condition_groups.map((group) => group.next_node)).toEqual([
                nodeOf(model, UUID.end).id,
            ]);
        });
    });
});
