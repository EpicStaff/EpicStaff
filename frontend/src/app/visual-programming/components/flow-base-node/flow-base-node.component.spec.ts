import { getDebugNode, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';
import { LlmConfigStorageService, SystemOneConfigStorageService } from '@shared/services';
import { of } from 'rxjs';

import { AgentDefinitionsApiService } from '../../../features/agent-definitions/services/agent-definitions-api.service';
import { GraphDto } from '../../../features/flows/models/graph.model';
import { GraphVersionSnapshot } from '../../../features/flows/models/graph-version-preview.model';
import { KeyValueTablesStorageService } from '../../../features/key-value-tables/services/key-value-tables-storage.service';
import { NO_FILE_ACCESS_TOOLTIP } from '../../core/helpers/storage-grants.util';
import { KeyValueMode } from '../../core/models/key-value-node.model';
import { NodeModel, SubGraphNodeModel } from '../../core/models/node.model';
import { FlowService } from '../../services/flow.service';
import { FlowDiffStateService } from '../../services/flow-diff-state.service';
import { FlowReadOnlyService } from '../../services/flow-readonly.service';
import { FlowSettingsService } from '../../services/flow-settings.service';
import { NodeDiffStatus } from '../../utils/diff';
import { mapGraphDtoToFlowModel } from '../../utils/load/map-graph-dto-to-flow-model';
import { mapDecisionTableNodeToModel } from '../../utils/load/nodes/decision-table-node.mapper';
import { mapGraphNoteToModel } from '../../utils/load/nodes/graph-note.mapper';
import { mapKeyValueNodeToModel } from '../../utils/load/nodes/key-value-node.mapper';
import { mapStartNodeToModel } from '../../utils/load/nodes/start-node.mapper';
import { mapSubGraphNodeToModel } from '../../utils/load/nodes/subgraph-node.mapper';
import { buildPreviewFlowModel } from '../../utils/load/snapshot/map-snapshot-to-graph-dto';
import { liveDecisionTable, liveGraph, liveNote, livePython } from '../../utils/testing/live-graph.fixture';
import { normalizedCssColor, WRONG_APPEARANCE } from '../../utils/testing/node-appearance.fixture';
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
    const tooltipOf = (element: HTMLElement): string => getDebugNode(element)!.injector.get(MatTooltip).message;

    function render(node: NodeModel, readOnly = false, noFileAccessNodeIds: string[] = []): void {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(readOnly) } },
                { provide: AgentDefinitionsApiService, useValue: { definitions: signal([]) } },
                { provide: LlmConfigStorageService, useValue: { isConfigsLoaded: signal(false), configs: signal([]) } },
                {
                    provide: SystemOneConfigStorageService,
                    useValue: { isConfigsLoaded: signal(false), configs: signal([]), getAllConfigs: () => of([]) },
                },
                {
                    provide: KeyValueTablesStorageService,
                    useValue: {
                        tables: signal([{ id: 3, name: 'Very very long table name' }]),
                        loadTables: () => of([]),
                    },
                },
            ],
        });
        vi.spyOn(TestBed.inject(FlowService), 'nodeIdsWithoutFileAccess').mockReturnValue(new Set(noFileAccessNodeIds));
        fixture = TestBed.createComponent(FlowBaseNodeComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
    }

    it('sums up mode, table and keys in the tab without the node number, the table name cut short, in full on hover', () => {
        render(KEY_VALUE_NODE);

        expect(summaryParts()).toEqual(['Write', 'Very very long tabl…', '2 keys']);
        expect(separators()).toEqual(['/', '/']);
        expect(summaryTab()!.textContent).not.toContain('#');
        expect(tooltipOf(summaryTab()!)).toBe('Write / Very very long table name / 2 keys');
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
            } as NodeModel);
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

        expect(tooltipOf(noTableBadge()!)).toBe('Select a table in the node panel');
    });

    const headerBadges = (): HTMLElement[] =>
        Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('.header .node-badge'));

    it('shows no badge on a node without warnings', () => {
        render(KEY_VALUE_NODE);

        expect(headerBadges()).toEqual([]);
    });

    it('shows a single warning as its own badge in the header, with its own tooltip', () => {
        render(NO_TABLE_NODE);

        expect(headerBadges().map((badge) => badge.textContent!.trim())).toEqual(['No table']);
        expect(tooltipOf(headerBadges()[0])).toBe('Select a table in the node panel');
    });

    it('folds several warnings into one chip that counts them and lists every message on its own bulleted line', () => {
        render(NO_TABLE_NODE, false, [NO_TABLE_NODE.id]);

        expect(headerBadges().map((badge) => badge.textContent!.trim())).toEqual(['2 issues']);
        expect(tooltipOf(headerBadges()[0])).toBe(
            [`• ${NO_FILE_ACCESS_TOOLTIP}`, '• Select a table in the node panel'].join('\n')
        );
        expect(getDebugNode(headerBadges()[0])!.injector.get(MatTooltip).tooltipClass).toBe('multiline-tooltip');
    });

    it('shows a node with no file access as one "No file access" badge with its tooltip', () => {
        render(KEY_VALUE_NODE, false, [KEY_VALUE_NODE.id]);

        const [badge] = headerBadges();
        expect(badge.textContent!.trim()).toBe('No file access');
        expect(tooltipOf(badge)).toBe(NO_FILE_ACCESS_TOOLTIP);
        expect(headerBadges()).toHaveLength(1);
    });

    it('makes a badge focusable and described by its tooltip text, keeping its visible label', () => {
        render(NO_TABLE_NODE, false, [NO_TABLE_NODE.id]);

        TestBed.tick();
        const [chip] = headerBadges();
        const description = document.getElementById(chip.getAttribute('aria-describedby')!);
        expect(chip.getAttribute('tabindex')).toBe('0');
        expect(chip.hasAttribute('aria-label')).toBe(false);
        expect(chip.textContent!.trim()).toBe('2 issues');
        expect(description!.textContent).toBe(tooltipOf(chip));
    });

    function hoverTitle(clientWidth: number, scrollWidth: number): MatTooltip {
        const name: HTMLElement = fixture.nativeElement.querySelector('.header .title__text');
        Object.defineProperty(name, 'clientWidth', { value: clientWidth, configurable: true });
        Object.defineProperty(name, 'scrollWidth', { value: scrollWidth, configurable: true });
        name.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        return getDebugNode(name)!.injector.get(MatTooltip);
    }

    it('shows the full name on hover only when it is cut off', () => {
        render({ ...NO_TABLE_NODE, node_name: 'A very very long key-value node name that cannot fit' });

        expect(hoverTitle(100, 300).disabled).toBe(false);
        expect(hoverTitle(300, 300).disabled).toBe(true);
    });

    it('flags a node without a table in a read-only flow without asking to pick one', () => {
        render(NO_TABLE_NODE, true);

        expect(tooltipOf(noTableBadge()!)).toBe('No table selected');
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
                    provide: SystemOneConfigStorageService,
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
    const tooltipDirective = (mark: HTMLElement): MatTooltip | null =>
        getDebugNode(mark)?.injector.get(MatTooltip, null, { self: true }) ?? null;
    /** The hover tooltip of a mark; empty when it has none. */
    const markTooltip = (mark: HTMLElement | null): string | null => mark && (tooltipDirective(mark)?.message ?? '');
    /** Whether a mark's tooltip can open (it is off while the mark yields to a summary tab). */
    const tooltipEnabled = (mark: HTMLElement): boolean => !(tooltipDirective(mark)?.disabled ?? true);

    function render(node: NodeModel, state: { status: NodeDiffStatus } | null, hasMissingReferences = false): void {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(true) } },
                { provide: AgentDefinitionsApiService, useValue: { definitions: signal([]) } },
                { provide: LlmConfigStorageService, useValue: { isConfigsLoaded: signal(false), configs: signal([]) } },
                { provide: KeyValueTablesStorageService, useValue: { tables: signal([]), loadTables: () => of([]) } },
            ],
        });
        TestBed.inject(FlowDiffStateService).setMissingReferenceNodeIds(new Set(hasMissingReferences ? [node.id] : []));
        TestBed.inject(FlowDiffStateService).setState(
            state && {
                nodes: new Map([[node.id, { ...state, fields: [], missingReferences: [] }]]),
                connections: new Map(),
                versionOnlyPortIds: new Set(),
                currentOnlyRoutePortIds: new Set(),
                nodeIdByKey: new Map(),
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
            expect(markTooltip(badge())).toBe(label);
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
        // It hides while the node is hovered, so its tooltip could only open over nothing.
        expect(tooltipEnabled(badge()!)).toBe(false);
    });

    it('keeps the badge of a node without a summary tab always shown', () => {
        render({ ...mapGraphNoteToModel(liveNote), ports: null, nodeNumber: 3 }, { status: 'added' });

        expect(badge()!.classList).not.toContain('diff-badge--yields-to-tab');
        expect(tooltipEnabled(badge()!)).toBe(true);
        expect(markTooltip(badge())).toBe('Restore adds this node');
        // The tooltip says what the label says, so a screen reader hears it once (Material describes after render).
        TestBed.tick();
        expect(badge()!.hasAttribute('aria-describedby')).toBe(false);
    });

    it('flags missing references apart from the status, on an unchanged node too', () => {
        render(NUMBERED_NODE, { status: 'unchanged' }, true);

        expect(badge()).toBeNull();
        expect(missingReferencesMarker()!.getAttribute('aria-label')).toBe(
            'This version uses items that no longer exist'
        );
        expect(markTooltip(missingReferencesMarker())).toBe('This version uses items that no longer exist');
    });

    // jsdom has no layout: the classes pick the spot, the positions are checked by eye.
    it.each([
        { kind: 'an added node', state: { status: 'added' as const }, besideBadge: true },
        { kind: 'a changed node', state: { status: 'changed' as const }, besideBadge: true },
        { kind: 'an unchanged node', state: { status: 'unchanged' as const }, besideBadge: false },
        { kind: 'a node on the Preview tab', state: null, besideBadge: false },
    ])('puts the missing-reference marker beside the badge only when $kind has one', ({ state, besideBadge }) => {
        render({ ...mapGraphNoteToModel(liveNote), ports: null }, state, true);

        expect(missingReferencesMarker()!.classList.contains('missing-references-marker--beside-badge')).toBe(
            besideBadge
        );
    });

    it('lets the marker give way to the summary tab of a Key-Value node, as the badge does', () => {
        render(NUMBERED_NODE, { status: 'changed' }, true);

        expect(missingReferencesMarker()!.classList).toContain('missing-references-marker--yields-to-tab');
        expect(badge()!.classList).toContain('diff-badge--yields-to-tab');
        expect(tooltipEnabled(missingReferencesMarker()!)).toBe(false);
    });

    it('keeps the marker of a node without a summary tab always shown', () => {
        render({ ...mapGraphNoteToModel(liveNote), ports: null }, null, true);

        expect(missingReferencesMarker()!.classList).not.toContain('missing-references-marker--yields-to-tab');
        expect(tooltipEnabled(missingReferencesMarker()!)).toBe(true);
        // Heard once: the tooltip repeats the label.
        TestBed.tick();
        expect(missingReferencesMarker()!.hasAttribute('aria-describedby')).toBe(false);
    });

    it('flags missing references on a plain version canvas, with no status mark', () => {
        render(NUMBERED_NODE, null, true);

        expect(missingReferencesMarker()).not.toBeNull();
        expect(badge()).toBeNull();
        expect(Array.from(host().classList).filter((name) => name.startsWith('diff-'))).toEqual([]);
    });

    it('shows no diff marks off a diff canvas, as in the live editor', () => {
        render(NUMBERED_NODE, null);

        expect(Array.from(host().classList).filter((name) => name.startsWith('diff-'))).toEqual([]);
        expect(badge()).toBeNull();
        expect(missingReferencesMarker()).toBeNull();
    });
});

describe('FlowBaseNodeComponent header', () => {
    function renderHeaderIcon(node: NodeModel): HTMLElement {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(false) } },
                { provide: AgentDefinitionsApiService, useValue: { definitions: signal([]) } },
                { provide: LlmConfigStorageService, useValue: { isConfigsLoaded: signal(false), configs: signal([]) } },
                { provide: KeyValueTablesStorageService, useValue: { tables: signal([]), loadTables: () => of([]) } },
            ],
        });
        const fixture = TestBed.createComponent(FlowBaseNodeComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
        return fixture.nativeElement.querySelector('.icon-wrapper i');
    }

    function expectTypeAppearance(icon: HTMLElement, type: NodeType): void {
        expect(icon.className).toBe(NODE_ICONS[type]);
        expect(icon.style.color).toBe(normalizedCssColor(NODE_COLORS[type]));
    }

    it("renders the type colour and icon, not the node's own", () => {
        const agentNode = {
            id: 'agent',
            backendId: null,
            type: NodeType.AGENT,
            node_name: 'Agent',
            data: { name: 'Agent', agent_definition: null, surface_list: [], inline_surface: null, tasks: [] },
            position: { x: 0, y: 0 },
            ports: [],
            ...WRONG_APPEARANCE,
            size: { width: 300, height: 200 },
            input_map: {},
            output_variable_path: null,
        } as unknown as NodeModel;

        const icon = renderHeaderIcon(agentNode);

        expect(icon.className).toBe('ti ti-robot');
        expectTypeAppearance(icon, NodeType.AGENT);
    });

    it('shows the type colour and icon for a loaded node whose backend metadata holds another colour and icon', () => {
        const staleGraph = {
            ...liveGraph,
            python_node_list: [{ ...livePython, metadata: { position: { x: 1, y: 2 }, ...WRONG_APPEARANCE } }],
        } as unknown as GraphDto;
        const loaded = mapGraphDtoToFlowModel(staleGraph).nodes.find((node) => node.type === NodeType.PYTHON)!;

        expectTypeAppearance(renderHeaderIcon(loaded), NodeType.PYTHON);
    });

    it('shows the type colour and icon for a version-preview node whose snapshot metadata holds another colour and icon', () => {
        const staleSnapshot = {
            nodes: [
                {
                    ...livePython,
                    node_type: 'PythonNode',
                    metadata: { position: { x: 1, y: 2 }, ...WRONG_APPEARANCE },
                },
            ],
            edge_list: [],
            metadata: {},
            secret_declarations: { nodes: {}, telegram: {} },
        } as unknown as GraphVersionSnapshot;
        const { flow } = buildPreviewFlowModel(staleSnapshot, new Map(), []);
        const previewed = flow.nodes.find((node) => node.type === NodeType.PYTHON)!;

        // Ports are drawn through foblex directives that need a flow canvas; the header does not depend on them.
        expectTypeAppearance(renderHeaderIcon({ ...previewed, ports: [] }), NodeType.PYTHON);
    });
});

describe('FlowBaseNodeComponent subflow node whose flow was deleted', () => {
    let fixture: ComponentFixture<FlowBaseNodeComponent>;

    const element = (selector: string): HTMLElement | null => fixture.nativeElement.querySelector(selector);

    // The backend nulls `subgraph` once the target flow is deleted; the loader then flags the node.
    const BLOCKED_SUBFLOW_NODE: SubGraphNodeModel = {
        ...mapSubGraphNodeToModel({
            id: 21,
            uuid: '00000000-0000-4000-8000-000000000021',
            created_at: '2026-01-01T00:00:00Z',
            node_number: 2,
            node_name: 'Billing',
            graph: 1,
            subgraph: null,
            subgraph_detail: null,
            input_map: {},
            output_variable_path: null,
            metadata: {},
            created_by: null,
            last_edited_by: null,
            last_edited_at: null,
        }),
        isBlocked: true,
    };
    const REATTACHED_SUBFLOW_NODE: SubGraphNodeModel = {
        ...BLOCKED_SUBFLOW_NODE,
        data: { id: 7, uuid: 'invoices-uuid', name: 'Invoices', description: '', tags: [] },
        isBlocked: false,
    };

    function render(node: NodeModel): void {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(false) } },
                { provide: AgentDefinitionsApiService, useValue: { definitions: signal([]) } },
                { provide: LlmConfigStorageService, useValue: { isConfigsLoaded: signal(false), configs: signal([]) } },
                { provide: KeyValueTablesStorageService, useValue: { tables: signal([]), loadTables: () => of([]) } },
            ],
        });
        fixture = TestBed.createComponent(FlowBaseNodeComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
    }

    function clickNodeBody(): void {
        const body = element('.interactive-node-body')!;
        body.dispatchEvent(new MouseEvent('mousedown', { clientX: 10, clientY: 10 }));
        body.dispatchEvent(new MouseEvent('mouseup', { clientX: 10, clientY: 10 }));
    }

    it('opens its panel on a click, so another flow can be chosen', () => {
        render(BLOCKED_SUBFLOW_NODE);
        const opened: NodeModel[] = [];
        fixture.componentInstance.editClicked.subscribe((node) => opened.push(node));

        clickNodeBody();

        expect(opened).toEqual([BLOCKED_SUBFLOW_NODE]);
    });

    it('keeps Unpack and Go to flow disabled and shows the missing-flow badge', () => {
        render(BLOCKED_SUBFLOW_NODE);
        let unpacked = 0;
        fixture.componentInstance.unpackClicked.subscribe(() => unpacked++);

        element('.unpack-button')!.click();

        expect(unpacked).toBe(0);
        expect(element('.unpack-button')!.classList).toContain('disabled');
        expect(element('.go-to-flow')).toBeNull();
        expect(element('.blocked-badge')!.textContent!.trim()).toBe('Missing flow');
        expect(element('.title')!.textContent!.trim()).toBe('Deleted Flow');
    });

    it("an attached subflow node enables Unpack and Go to flow and shows its flow's name", () => {
        render(REATTACHED_SUBFLOW_NODE);
        let unpacked = 0;
        fixture.componentInstance.unpackClicked.subscribe(() => unpacked++);

        element('.unpack-button')!.click();

        expect(unpacked).toBe(1);
        expect(element('.unpack-button')!.classList).not.toContain('disabled');
        expect(element('.go-to-flow a')!.getAttribute('href')).toBe('/flows/7');
        expect(element('.blocked-badge')).toBeNull();
        expect(element('.title')!.textContent!.trim()).toBe('Invoices');
    });
});
