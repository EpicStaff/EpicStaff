import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NODE_COLORS, NodeType } from '@shared/models';
import { LlmConfigStorageService } from '@shared/services';
import { of } from 'rxjs';

import { AgentDefinitionsApiService } from '../../../features/agent-definitions/services/agent-definitions-api.service';
import { KeyValueTablesStorageService } from '../../../features/key-value-tables/services/key-value-tables-storage.service';
import { KeyValueMode } from '../../core/models/key-value-node.model';
import { NodeModel } from '../../core/models/node.model';
import { FlowService } from '../../services/flow.service';
import { FlowDiffStateService } from '../../services/flow-diff-state.service';
import { FlowReadOnlyService } from '../../services/flow-readonly.service';
import { FlowSettingsService } from '../../services/flow-settings.service';
import { NodeDiffStatus } from '../../utils/diff';
import { mapDecisionTableNodeToModel } from '../../utils/load/nodes/decision-table-node.mapper';
import { mapGraphNoteToModel } from '../../utils/load/nodes/graph-note.mapper';
import { mapKeyValueNodeToModel } from '../../utils/load/nodes/key-value-node.mapper';
import { mapStartNodeToModel } from '../../utils/load/nodes/start-node.mapper';
import { liveDecisionTable, liveNote } from '../../utils/testing/live-graph.fixture';
import { FlowBaseNodeComponent } from './flow-base-node.component';

const KEY_VALUE_NODE = {
    ...mapKeyValueNodeToModel({
        id: 12,
        uuid: '00000000-0000-4000-8000-000000000012',
        graph: 1,
        node_number: 1,
        node_name: 'Key-Value',
        key_value_table: 3,
        mode: 'write',
        entries: [
            { key: 'profile', value: 'variables.user' },
            { key: 'plan', value: 'variables.plan' },
        ],
        input_map: {},
        output_variable_path: null,
        metadata: {},
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
        last_edited_by: null,
        last_edited_at: null,
    }),
    nodeNumber: 1,
};

describe('FlowBaseNodeComponent key-value summary', () => {
    let fixture: ComponentFixture<FlowBaseNodeComponent>;

    const summaryTab = (): HTMLElement | null => fixture.nativeElement.querySelector('.key-value-summary-tab');
    const summaryParts = (): string[] =>
        Array.from<HTMLElement>(summaryTab()!.querySelectorAll('.summary > span:not(.summary-separator)')).map((part) =>
            part.textContent!.trim()
        );
    const separators = (): string[] =>
        Array.from<HTMLElement>(summaryTab()!.querySelectorAll('.summary-separator')).map((separator) =>
            separator.textContent!.trim()
        );
    const noTableBadge = (): HTMLElement | undefined =>
        Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('.llm-warning-badge')).find(
            (badge) => badge.textContent!.trim() === 'No table'
        );

    function render(node: NodeModel, readOnly = false): void {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(readOnly) } },
                { provide: AgentDefinitionsApiService, useValue: { definitions: signal([]) } },
                { provide: LlmConfigStorageService, useValue: { isConfigsLoaded: signal(false), configs: signal([]) } },
                {
                    provide: KeyValueTablesStorageService,
                    useValue: {
                        tables: signal([{ id: 3, name: 'Very very long table name' }]),
                        loadTables: () => of([]),
                    },
                },
            ],
        });
        fixture = TestBed.createComponent(FlowBaseNodeComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
    }

    it('sums up mode, table and keys in the tab without the node number, the table name cut short, in full on hover', () => {
        render(KEY_VALUE_NODE);

        expect(summaryParts()).toEqual(['Write', 'Very very long tabl…', '2 keys']);
        expect(separators()).toEqual(['/', '/']);
        expect(summaryTab()!.textContent).not.toContain('#');
        expect(summaryTab()!.title).toBe('Write / Very very long table name / 2 keys');
    });

    it('reads the summary once to screen readers, from the header icon, with the table name in full', () => {
        render(KEY_VALUE_NODE);

        expect(summaryTab()!.querySelector('.summary')!.getAttribute('aria-hidden')).toBe('true');
        expect(fixture.nativeElement.querySelector('.icon-wrapper [role="img"]').getAttribute('aria-label')).toBe(
            'Write / Very very long table name / 2 keys'
        );
    });

    const MODE_STRIPES: Record<KeyValueMode, string> = {
        read: 'var(--success-color)',
        write: 'var(--color-status-processing)',
        delete: 'var(--color-status-error)',
    };
    for (const mode of Object.keys(MODE_STRIPES) as KeyValueMode[]) {
        it(`draws the type's database icon in its colour in ${mode}, with the mode only on the left stripe`, () => {
            // Neither a saved icon nor a saved colour is what the header shows.
            render({
                ...KEY_VALUE_NODE,
                icon: 'ti ti-database-x',
                color: '#000000',
                data: { ...KEY_VALUE_NODE.data, mode },
            });
            const icon: HTMLElement = fixture.nativeElement.querySelector('.icon-wrapper i');
            const typeColor = document.createElement('i');
            typeColor.style.color = NODE_COLORS[NodeType.KEY_VALUE];

            expect(icon.className).toBe('ti ti-database');
            expect(icon.style.color).toBe(typeColor.style.color);
            expect(
                fixture.nativeElement
                    .querySelector('.interactive-node-body')
                    .style.getPropertyValue('--key-value-accent')
            ).toBe(MODE_STRIPES[mode]);
        });
    }

    const NO_TABLE_NODE = { ...KEY_VALUE_NODE, data: { ...KEY_VALUE_NODE.data, key_value_table: null } };

    it('flags a node without a table and says where to pick one', () => {
        render(NO_TABLE_NODE);

        expect(noTableBadge()!.title).toBe('Select a table in the node panel');
    });

    it('flags a node without a table in a read-only flow without asking to pick one', () => {
        render(NO_TABLE_NODE, true);

        expect(noTableBadge()!.title).toBe('No table selected');
    });

    it('is only for key-value nodes', () => {
        render({
            ...mapStartNodeToModel({
                id: 1,
                uuid: '00000000-0000-4000-8000-000000000001',
                created_at: '2026-01-01T00:00:00Z',
                graph: 1,
                node_name: '__start__',
                variables: {},
                metadata: {},
                created_by: null,
                last_edited_by: null,
                last_edited_at: null,
            }),
            ports: null,
        });

        expect(summaryTab()).toBeNull();
    });
});

describe('FlowBaseNodeComponent node number', () => {
    let fixture: ComponentFixture<FlowBaseNodeComponent>;
    let settings: FlowSettingsService;

    const element = (selector: string): HTMLElement | null => fixture.nativeElement.querySelector(selector);
    const text = (selector: string): string | undefined => element(selector)?.textContent?.trim();
    const numberLine = (): string | undefined => text('.title-column .node-number-line');
    const titleColumnClasses = (): DOMTokenList => element('.title-column')!.classList;

    function render(node: NodeModel, { alwaysShow = false, otherNodes = [] as NodeModel[] } = {}): void {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(false) } },
                { provide: AgentDefinitionsApiService, useValue: { definitions: signal([]) } },
                {
                    provide: LlmConfigStorageService,
                    useValue: { isConfigsLoaded: signal(false), configs: signal([]), getAllConfigs: () => of([]) },
                },
                {
                    provide: KeyValueTablesStorageService,
                    useValue: { tables: signal([]), loadTables: () => of([]) },
                },
            ],
        });
        settings = TestBed.inject(FlowSettingsService);
        settings.alwaysShowNodeNumbers.set(alwaysShow);
        TestBed.inject(FlowService).setFlow({ nodes: [node, ...otherNodes], connections: [] });
        fixture = TestBed.createComponent(FlowBaseNodeComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
    }

    const pythonNode = { id: 'fetch', type: NodeType.PYTHON, node_name: 'Fetch', nodeNumber: 3 } as NodeModel;

    const tableLikeNode = (type: NodeType, overrides: Record<string, unknown> = {}): NodeModel =>
        ({
            id: 'table',
            backendId: null,
            type,
            node_name: 'Route',
            nodeNumber: 3,
            data: { name: 'Route', table: { default_next_node: null, next_error_node: null, condition_groups: [] } },
            position: { x: 0, y: 0 },
            ports: [],
            color: '',
            icon: '',
            size: { width: 300, height: 200 },
            input_map: {},
            output_variable_path: null,
            ...overrides,
        }) as unknown as NodeModel;

    const NODE_TITLE = '.interactive-node-body .title';
    const TABLE_TITLE = '.decision-table__header .title';

    beforeEach(() => localStorage.clear());

    // Hover and the name's glide are CSS (:hover, transform), which jsdom does not apply: these tests pin
    // the DOM and the classes the styles key on — `has-node-number` (lifts on hover) and `is-number-pinned`.
    describe.each([
        { kind: 'a Python node', node: pythonNode, titleSelector: NODE_TITLE, name: 'Fetch' },
        {
            kind: 'a Key-Value node',
            node: { ...KEY_VALUE_NODE, nodeNumber: 3 },
            titleSelector: NODE_TITLE,
            name: 'Key-Value',
        },
        { kind: 'a decision table', node: tableLikeNode(NodeType.TABLE), titleSelector: TABLE_TITLE, name: 'Route' },
        {
            kind: 'a classification table',
            node: tableLikeNode(NodeType.CLASSIFICATION_TABLE),
            titleSelector: TABLE_TITLE,
            name: 'Route',
        },
    ])('on $kind', ({ node, titleSelector, name }) => {
        it.each([false, true])(
            'titles the node with its name only and puts "#N" under it (always shown: %s)',
            (alwaysShow) => {
                render(node, { alwaysShow });

                expect(text(titleSelector)).toBe(name);
                expect(numberLine()).toBe('#3');
            }
        );

        // Only the pin is checkable here: showing the number on hover is a CSS :hover rule, which jsdom does not apply.
        it('pins the number while the setting is on, and unpins it when the setting goes off', () => {
            render(node);
            expect(titleColumnClasses()).toContain('has-node-number');
            expect(titleColumnClasses()).not.toContain('is-number-pinned');

            settings.alwaysShowNodeNumbers.set(true);
            fixture.detectChanges();
            expect(titleColumnClasses()).toContain('is-number-pinned');

            settings.alwaysShowNodeNumbers.set(false);
            fixture.detectChanges();
            expect(titleColumnClasses()).not.toContain('is-number-pinned');
        });

        it('has no number in the bar above the node, and keeps its delete chip there', () => {
            render(node, { alwaysShow: true });

            expect(text('.node-action-bar')).not.toContain('#');
            expect(element('.node-action-bar .delete-button')).not.toBeNull();
        });
    });

    it.each([
        { kind: 'a node without a number', node: { ...pythonNode, nodeNumber: undefined } },
        { kind: 'the End node', node: { id: 'end', type: NodeType.END, node_name: 'End', nodeNumber: 5 } as NodeModel },
        { kind: 'a table without a number', node: tableLikeNode(NodeType.TABLE, { nodeNumber: undefined }) },
    ])('shows no number on $kind, and its name stays centred alone', ({ node }) => {
        render(node, { alwaysShow: true });

        expect(numberLine()).toBeUndefined();
        expect(titleColumnClasses()).not.toContain('has-node-number');
        expect(titleColumnClasses()).not.toContain('is-number-pinned');
    });

    it.each([
        { type: NodeType.TABLE, fallback: 'Decision Table' },
        { type: NodeType.CLASSIFICATION_TABLE, fallback: 'Classification Table' },
    ])('titles a $type node without a name with its default title, and still shows "#N"', ({ type, fallback }) => {
        render(tableLikeNode(type, { node_name: '' }), { alwaysShow: true });

        expect(text(TABLE_TITLE)).toBe(fallback);
        expect(numberLine()).toBe('#3');
    });

    // The node body squares the corner the tab sits on, so only a node with a tab may be marked.
    it.each([
        { kind: 'a Key-Value node', node: KEY_VALUE_NODE, hasTab: true },
        { kind: 'a Python node', node: pythonNode, hasTab: false },
    ])('draws the tab above the node only for $kind with a summary', ({ node, hasTab }) => {
        render(node);

        expect(element('.key-value-summary-tab') !== null).toBe(hasTab);
        expect(element('.interactive-node-body')!.classList.contains('has-summary-tab')).toBe(hasTab);
    });

    it('names the next node of a decision table with its number, so same-named nodes are told apart', () => {
        const fetchNode = { id: 'fetch', type: NodeType.PYTHON, node_name: 'Fetch', nodeNumber: 4 } as NodeModel;
        const tableNode = tableLikeNode(NodeType.TABLE, {
            data: { name: 'Route', table: { default_next_node: 'fetch', next_error_node: null, condition_groups: [] } },
        });

        render(tableNode, { otherNodes: [fetchNode, { ...fetchNode, id: 'fetch-again', nodeNumber: 9 }] });

        expect(text('.decision-table__group .group-status')).toBe('(Fetch #4)');
    });
});

describe('FlowBaseNodeComponent on a version diff canvas', () => {
    let fixture: ComponentFixture<FlowBaseNodeComponent>;

    const NUMBERED_NODE = { ...KEY_VALUE_NODE, id: 'key-value-node' };
    const host = (): HTMLElement => fixture.nativeElement;
    const badge = (): HTMLElement | null => host().querySelector('.diff-badge');
    const missingReferencesMarker = (): HTMLElement | null => host().querySelector('.missing-references-marker');

    function render(node: NodeModel, state: { status: NodeDiffStatus; hasMissingReferences?: boolean } | null): void {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(true) } },
                { provide: AgentDefinitionsApiService, useValue: { definitions: signal([]) } },
                { provide: LlmConfigStorageService, useValue: { isConfigsLoaded: signal(false), configs: signal([]) } },
                { provide: KeyValueTablesStorageService, useValue: { tables: signal([]), loadTables: () => of([]) } },
            ],
        });
        TestBed.inject(FlowDiffStateService).setState(
            state && {
                nodes: new Map([[node.id, { hasMissingReferences: false, ...state }]]),
                connections: new Map(),
                versionOnlyPortIds: new Set(),
            }
        );
        fixture = TestBed.createComponent(FlowBaseNodeComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
    }

    const BADGES: { status: NodeDiffStatus; label: string | null }[] = [
        { status: 'added', label: 'Restore adds this node' },
        { status: 'deleted', label: 'Restore removes this node' },
        { status: 'changed', label: 'Restore changes this node' },
        { status: 'unchanged', label: null },
    ];
    for (const { status, label } of BADGES) {
        it(`marks a ${status} node with one status class and ${label ? `a "${label}" badge` : 'no badge'}`, () => {
            render(NUMBERED_NODE, { status });

            const statusClasses = Array.from(host().classList).filter((name) => name.startsWith('diff-'));
            expect(statusClasses).toEqual([`diff-${status}`]);
            expect(badge()?.getAttribute('aria-label') ?? null).toBe(label);
            expect(badge()?.title ?? null).toBe(label);
        });
    }

    const NODES_OF_EVERY_LAYOUT: { layout: string; node: NodeModel }[] = [
        { layout: 'a note', node: { ...mapGraphNoteToModel(liveNote), ports: null } },
        { layout: 'a decision table', node: { ...mapDecisionTableNodeToModel(liveDecisionTable), ports: null } },
    ];
    for (const { layout, node } of NODES_OF_EVERY_LAYOUT) {
        it(`marks ${layout} too`, () => {
            render(node, { status: 'deleted' });

            expect(host().classList).toContain('diff-deleted');
            expect(badge()?.getAttribute('aria-label')).toBe('Restore removes this node');
        });
    }

    it('lets the badge give way to the summary tab of a Key-Value node, which takes the top-left corner', () => {
        render(NUMBERED_NODE, { status: 'added' });

        expect(badge()!.classList).toContain('diff-badge--yields-to-tab');
    });

    it('keeps the badge of a node without a summary tab always shown', () => {
        render({ ...mapGraphNoteToModel(liveNote), ports: null, nodeNumber: 3 }, { status: 'added' });

        expect(badge()!.classList).not.toContain('diff-badge--yields-to-tab');
    });

    it('flags missing references apart from the status, on an unchanged node too', () => {
        render(NUMBERED_NODE, { status: 'unchanged', hasMissingReferences: true });

        expect(badge()).toBeNull();
        expect(missingReferencesMarker()!.getAttribute('aria-label')).toBe(
            'This version used items that no longer exist'
        );
    });

    it('shows no diff marks off a diff canvas, as in the live editor', () => {
        render(NUMBERED_NODE, null);

        expect(Array.from(host().classList).filter((name) => name.startsWith('diff-'))).toEqual([]);
        expect(badge()).toBeNull();
        expect(missingReferencesMarker()).toBeNull();
    });
});
