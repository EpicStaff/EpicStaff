import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { PANEL_COMPONENT_MAP } from '../../core/enums/node-panel.map';
import { KeyValueNodeModel, NodeModel } from '../../core/models/node.model';
import { FieldChange, FieldName } from '../../utils/diff';
import { isNestedField, SEMANTIC_PROJECTIONS } from '../../utils/diff/semantic-projections';
import {
    fieldChange,
    liveNodeOfType,
    openPanelOnChangesTab,
    respond,
    SHOWN_DIFF_MARKS,
} from './node-panel-diff.testing';

// Drift guard: every field the version diff compares has a mark in its node's panel, so a changed node never opens a
// panel that shows nothing of what a restore changes. A field added to a projection (`semantic-projections.ts`)
// without a mark in its panel fails here. For each field the panel is opened on the Changes tab with only that
// field changed, narrow and widened (some panels lay out other content when widened); it must then show a mark of
// some kind (a field mark, an Input List or Key-Value row, a note under a list, a code diff).

/** Fields a panel shows no mark for on purpose, by node type, each with the reason. */
const NO_MARK_ON_PURPOSE: Partial<Record<NodeType, Partial<Record<FieldName, string>>>> = {
    [NodeType.PYTHON]: { 'python_code.entrypoint': 'no panel shows the entrypoint: it is always main' },
    [NodeType.WEBHOOK_TRIGGER]: { 'python_code.entrypoint': 'no panel shows the entrypoint: it is always main' },
};

/** Node types with no panel, each with the reason and where their diff shows instead. */
const WITHOUT_PANEL: Partial<Record<NodeType, string>> = {
    [NodeType.START]: 'opens the Domain window, which shows changed variables as a diff (domain-dialog spec)',
    [NodeType.NOTE]: 'the note window does not open in a version preview: the canvas badge only (known limit)',
    [NodeType.TOOL]: 'never loaded from or saved to the backend',
};

/**
 * Panels whose field marks come in a later step of this feature (Agent, Task and Schedule; the decision tables with
 * their grids). This list must be empty once those steps are done.
 */
const MARKS_PENDING: readonly NodeType[] = [
    NodeType.AGENT,
    NodeType.TASK,
    NodeType.SCHEDULE_TRIGGER,
    NodeType.TABLE,
    NodeType.CLASSIFICATION_TABLE,
];

/** What a panel needs from the backend to show every field of the version, e.g. the RAG search settings. */
const LOAD_OPTIONS: Partial<Record<NodeType, () => void>> = {
    [NodeType.KNOWLEDGE_RETRIEVER]: () => {
        respond('source-collections/5/available-rags/', [
            { rag_id: 8, rag_type: 'naive', rag_status: 'completed', collection_id: 5 },
        ]);
    },
};

/**
 * List fields whose rows the panel pairs by a key of their own while the list runs in order: a reorder alone changes
 * no row, and the panel must still show it. Each with a version node whose list has rows with different keys.
 */
const REORDERED_LISTS: readonly { type: NodeType; field: FieldName; node: NodeModel }[] = [
    {
        type: NodeType.KEY_VALUE,
        field: 'entries',
        node: withKeyValueEntries([
            { key: 'customer', value: 'variables.customer' },
            { key: 'order', value: 'variables.order' },
        ]),
    },
];

/** Panels lay out other content when widened (End and Webhook editors, Knowledge templates); both must mark. */
const LAYOUTS = [
    { layout: 'narrow', expanded: false },
    { layout: 'widened', expanded: true },
] as const;

const GUARDED_TYPES = Object.values(NodeType).filter(
    (type) => Object.hasOwn(PANEL_COMPONENT_MAP, type) && !MARKS_PENDING.includes(type)
);

// jsdom has no ResizeObserver; the decision table panels' directives only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function withKeyValueEntries(entries: KeyValueNodeModel['data']['entries']): NodeModel {
    const node = liveNodeOfType(NodeType.KEY_VALUE) as KeyValueNodeModel;
    return { ...node, data: { ...node.data, entries } };
}

/** What the version diff compares of `node` (by default the live graph fixture's node of the type: the version side). */
function projectionOf(type: NodeType, node: NodeModel = liveNodeOfType(type)): Record<string, unknown> {
    const projection = SEMANTIC_PROJECTIONS[type] as { project: (...args: unknown[]) => Record<string, unknown> };
    return projection.project(node, { nodeKey: (canvasId: unknown) => canvasId });
}

/** Every field the version diff compares for the node type, a nested field by each of its parts. */
function diffedFieldsOf(type: NodeType): FieldName[] {
    return Object.entries(projectionOf(type)).flatMap(([field, value]) =>
        isNestedField(field) && value !== null && typeof value === 'object'
            ? Object.keys(value).map((part) => `${field}.${part}` as FieldName)
            : [field as FieldName]
    );
}

/** A canvas value other than the version's, of the same shape, so the panel has something to show as changed. */
function otherValueThan(version: unknown): unknown {
    if (version === null || version === undefined) return 'canvas value';
    if (typeof version === 'string') return `${version} (canvas)`;
    if (typeof version === 'number') return version + 1;
    if (typeof version === 'boolean') return !version;
    if (Array.isArray(version)) return version.length > 0 ? [] : ['canvas item'];
    return { ...(version as object), canvas_only: 'variables.canvas' };
}

function versionValueOf(type: NodeType, field: FieldName, node?: NodeModel): unknown {
    const projection = projectionOf(type, node);
    const [top, part] = field.split('.');
    return part === undefined ? projection[top] : (projection[top] as Record<string, unknown> | null)?.[part];
}

/** The diffed fields of the type that must have a mark (the ones not left without one on purpose). */
function fieldsToMarkOf(type: NodeType): FieldName[] {
    return diffedFieldsOf(type).filter((field) => !Object.hasOwn(NO_MARK_ON_PURPOSE[type] ?? {}, field));
}

/** A change of `field` alone: the version holds `node`'s value, the canvas another of the same shape. */
function changeOf(type: NodeType, field: FieldName, node?: NodeModel): FieldChange {
    const version = versionValueOf(type, field, node);
    return fieldChange(field, otherValueThan(version), version);
}

/** How many marks the panel of `node` shows on the Changes tab when a restore makes `change` alone. */
function shownMarkCount(type: NodeType, node: NodeModel, change: FieldChange, expanded: boolean): number {
    const fixture = openPanelOnChangesTab(PANEL_COMPONENT_MAP[type], node, [change], { expanded });
    LOAD_OPTIONS[type]?.();
    fixture.detectChanges();
    const count = (fixture.nativeElement as HTMLElement).querySelectorAll(SHOWN_DIFF_MARKS).length;
    fixture.destroy();
    // So one test can open a panel again.
    TestBed.resetTestingModule();
    return count;
}

describe('Node panel field marks: drift guard', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('knows every node type: guarded by its panel, pending, or without a panel', () => {
        for (const type of Object.values(NodeType)) {
            const hasPanel = Object.hasOwn(PANEL_COMPONENT_MAP, type);
            expect(
                hasPanel !== Object.hasOwn(WITHOUT_PANEL, type),
                `Node type ${type}: give it a panel, or add it to WITHOUT_PANEL with the reason`
            ).toBe(true);
        }
        for (const type of MARKS_PENDING) {
            expect(Object.hasOwn(PANEL_COMPONENT_MAP, type), `Pending node type ${type} has no panel`).toBe(true);
        }
    });

    it('allows only fields the version diff compares to go without a mark', () => {
        for (const [type, fields] of Object.entries(NO_MARK_ON_PURPOSE)) {
            const diffed = diffedFieldsOf(type as NodeType);
            for (const field of Object.keys(fields ?? {})) {
                expect(
                    diffed,
                    `${field} is not a diffed field of ${type}: remove it from NO_MARK_ON_PURPOSE`
                ).toContain(field);
            }
        }
    });

    const CASES = GUARDED_TYPES.flatMap((type) =>
        fieldsToMarkOf(type).flatMap((field) =>
            LAYOUTS.map(({ layout, expanded }) => ({
                type,
                field,
                layout,
                expanded,
                panel: PANEL_COMPONENT_MAP[type].name.replace(/^_/, ''),
            }))
        )
    );

    it.each(CASES)(
        '$type panel, $layout, marks $field when a restore changes it',
        ({ type, field, layout, expanded, panel }) => {
            const node = liveNodeOfType(type);

            expect(
                shownMarkCount(type, node, changeOf(type, field), expanded),
                `${panel} (${layout}) shows nothing when a restore changes ${field}: wrap the field in ` +
                    '<app-diff-field-mark> (or give its rows a status), or add it to NO_MARK_ON_PURPOSE with the reason'
            ).toBeGreaterThan(0);
        }
    );

    const REORDER_CASES = REORDERED_LISTS.flatMap((list) => LAYOUTS.map((layout) => ({ ...list, ...layout })));

    it.each(REORDER_CASES)(
        '$type panel, $layout, shows a restore that only reorders $field',
        ({ type, field, node, layout, expanded }) => {
            const version = versionValueOf(type, field, node) as unknown[];
            expect(version.length, `the ${field} of the ${type} case need two rows to reorder`).toBeGreaterThan(1);

            expect(
                shownMarkCount(type, node, fieldChange(field, [...version].reverse(), version), expanded),
                `${PANEL_COMPONENT_MAP[type].name.replace(/^_/, '')} (${layout}) shows nothing when a restore ` +
                    `only reorders ${field}: its rows are paired by key, so show the order change (a note)`
            ).toBeGreaterThan(0);
        }
    );

    it.each(MARKS_PENDING)('%s is still pending: some diffed field of its panel has no mark yet', (type) => {
        const node = liveNodeOfType(type);
        const allMarked = fieldsToMarkOf(type).every((field) =>
            LAYOUTS.every(({ expanded }) => shownMarkCount(type, node, changeOf(type, field), expanded) > 0)
        );

        expect(allMarked, `Every diffed field of the ${type} panel is marked: remove ${type} from MARKS_PENDING`).toBe(
            false
        );
    });
});
