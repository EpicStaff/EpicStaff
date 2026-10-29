import { NodeType } from '@shared/models';

import { DecisionTableNodeModel } from '../models/node.model';
import { convertDecisionTableToCdt } from './dt-to-cdt-converter';

function makeDtNode(overrides: Partial<DecisionTableNodeModel> = {}): DecisionTableNodeModel {
    return {
        id: 'dt-id-1',
        backendId: 100,
        type: NodeType.TABLE,
        node_name: 'My DT',
        position: { x: 100, y: 200 },
        size: { width: 330, height: 300 },
        color: '#old-color',
        icon: 'old-icon',
        ports: null,
        input_map: { key: 'value' },
        output_variable_path: 'some.path',
        nodeNumber: 5,
        data: {
            name: 'My DT',
            table: {
                default_next_node: 'node-abc',
                next_error_node: 'node-err',
                condition_groups: [],
            },
        },
        ...overrides,
    };
}

describe('convertDecisionTableToCdt', () => {
    it('creates a new node with a fresh UUID and null backendId', () => {
        const dt = makeDtNode();
        const { node } = convertDecisionTableToCdt(dt);

        expect(node.id).not.toBe(dt.id);
        expect(node.id.length).toBeGreaterThan(0);
        expect(node.backendId).toBeNull();
    });

    it('sets the type to CLASSIFICATION_TABLE', () => {
        const { node } = convertDecisionTableToCdt(makeDtNode());
        expect(node.type).toBe(NodeType.CLASSIFICATION_TABLE);
    });

    it('preserves position, node_name, input_map, output_variable_path, and nodeNumber', () => {
        const dt = makeDtNode();
        const { node } = convertDecisionTableToCdt(dt);

        expect(node.position).toEqual({ x: 100, y: 200 });
        expect(node.node_name).toBe('My DT');
        expect(node.input_map).toEqual({ key: 'value' });
        expect(node.output_variable_path).toBe('some.path');
        expect(node.nodeNumber).toBe(5);
    });

    it('carries over default_next_node and next_error_node', () => {
        const dt = makeDtNode();
        const { node } = convertDecisionTableToCdt(dt);

        expect(node.data.table.default_next_node).toBe('node-abc');
        expect(node.data.table.next_error_node).toBe('node-err');
    });

    it('initialises CDT-only fields to safe defaults', () => {
        const { node } = convertDecisionTableToCdt(makeDtNode());
        const table = node.data.table;

        expect(table.route_variable_name).toBe('route_code');
        expect(table.default_llm_config).toBeNull();
        expect(table.prompts).toEqual({});
        expect(table.pre_computation_code).toBe('');
        expect(table.pre_computation).toEqual({ code: '', input_map: {} });
        expect(table.post_computation).toEqual({ code: '', input_map: {} });
    });

    it('auto-assigns route_code from the group name when not set', () => {
        const dt = makeDtNode({
            data: {
                name: 'dt',
                table: {
                    default_next_node: null,
                    next_error_node: null,
                    condition_groups: [
                        {
                            group_name: 'Is Premium',
                            group_type: 'simple',
                            expression: null,
                            conditions: [],
                            manipulation: null,
                            next_node: null,
                        },
                    ],
                },
            },
        });

        const { node } = convertDecisionTableToCdt(dt);
        expect(node.data.table.condition_groups[0].route_code).toBe('Route code for Is Premium');
    });

    it('preserves existing route_code values', () => {
        const dt = makeDtNode({
            data: {
                name: 'dt',
                table: {
                    default_next_node: null,
                    next_error_node: null,
                    condition_groups: [
                        {
                            group_name: 'Check',
                            group_type: 'simple',
                            expression: null,
                            conditions: [],
                            manipulation: null,
                            next_node: null,
                            route_code: 'existing-code',
                        },
                    ],
                },
            },
        });

        const { node } = convertDecisionTableToCdt(dt);
        expect(node.data.table.condition_groups[0].route_code).toBe('existing-code');
    });

    it('deduplicates route_code values by appending the index', () => {
        const dt = makeDtNode({
            data: {
                name: 'dt',
                table: {
                    default_next_node: null,
                    next_error_node: null,
                    condition_groups: [
                        {
                            group_name: 'Same',
                            group_type: 'simple',
                            expression: null,
                            conditions: [],
                            manipulation: null,
                            next_node: null,
                            route_code: 'duplicate',
                        },
                        {
                            group_name: 'Same',
                            group_type: 'simple',
                            expression: null,
                            conditions: [],
                            manipulation: null,
                            next_node: null,
                            route_code: 'duplicate',
                        },
                    ],
                },
            },
        });

        const { node } = convertDecisionTableToCdt(dt);
        const codes = node.data.table.condition_groups.map((g) => g.route_code);
        expect(codes[0]).toBe('duplicate');
        expect(codes[1]).toBe('duplicate 2');
    });

    it('sets valid to true on all condition groups', () => {
        const dt = makeDtNode({
            data: {
                name: 'dt',
                table: {
                    default_next_node: null,
                    next_error_node: null,
                    condition_groups: [
                        {
                            group_name: '',
                            group_type: 'simple',
                            expression: null,
                            conditions: [],
                            manipulation: null,
                            next_node: null,
                            valid: false,
                        },
                    ],
                },
            },
        });

        const { node } = convertDecisionTableToCdt(dt);
        expect(node.data.table.condition_groups[0].valid).toBe(true);
    });

    describe('port remapping', () => {
        it('maps DT per-rule output ports to CDT route ports', () => {
            const dt = makeDtNode({
                data: {
                    name: 'dt',
                    table: {
                        default_next_node: null,
                        next_error_node: null,
                        condition_groups: [
                            {
                                group_name: 'Check A',
                                group_type: 'simple',
                                expression: null,
                                conditions: [],
                                manipulation: null,
                                next_node: null,
                            },
                        ],
                    },
                },
            });

            const { node, portIdMap } = convertDecisionTableToCdt(dt);
            const oldPortId = `${dt.id}_decision-out-check-a`;
            expect(portIdMap[oldPortId]).toBeDefined();
            // The new port id should reference the new node id and use the route code slug
            expect(portIdMap[oldPortId]).toContain(node.id);
            expect(portIdMap[oldPortId]).toContain('decision-route-');
        });

        it('creates a mapping entry for every condition group', () => {
            const dt = makeDtNode({
                data: {
                    name: 'dt',
                    table: {
                        default_next_node: null,
                        next_error_node: null,
                        condition_groups: [
                            {
                                group_name: 'A',
                                group_type: 'simple',
                                expression: null,
                                conditions: [],
                                manipulation: null,
                                next_node: null,
                            },
                            {
                                group_name: 'B',
                                group_type: 'simple',
                                expression: null,
                                conditions: [],
                                manipulation: null,
                                next_node: null,
                            },
                        ],
                    },
                },
            });

            const { portIdMap } = convertDecisionTableToCdt(dt);
            expect(Object.keys(portIdMap)).toHaveLength(2);
        });
    });

    it('generates ports for the new CDT node', () => {
        const dt = makeDtNode({
            data: {
                name: 'dt',
                table: {
                    default_next_node: null,
                    next_error_node: null,
                    condition_groups: [
                        {
                            group_name: 'Row 1',
                            group_type: 'simple',
                            expression: null,
                            conditions: [],
                            manipulation: null,
                            next_node: null,
                        },
                    ],
                },
            },
        });

        const { node } = convertDecisionTableToCdt(dt);
        expect(node.ports).not.toBeNull();
        expect(node.ports!.length).toBeGreaterThan(0);
    });

    it('defaults empty group_name to "Condition N"', () => {
        const dt = makeDtNode({
            data: {
                name: 'dt',
                table: {
                    default_next_node: null,
                    next_error_node: null,
                    condition_groups: [
                        {
                            group_name: '',
                            group_type: 'simple',
                            expression: null,
                            conditions: [],
                            manipulation: null,
                            next_node: null,
                        },
                    ],
                },
            },
        });

        const { node } = convertDecisionTableToCdt(dt);
        expect(node.data.table.condition_groups[0].group_name).toBe('Condition 1');
    });
});
