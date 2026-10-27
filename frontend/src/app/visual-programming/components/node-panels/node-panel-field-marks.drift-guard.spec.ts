import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { PANEL_COMPONENT_MAP } from '../../core/enums/node-panel.map';
import { KeyValueNodeModel, NodeModel } from '../../core/models/node.model';
import { FieldChange, FieldName } from '../../utils/diff';
import { isNestedField, keyPrefixOf, SEMANTIC_PROJECTIONS } from '../../utils/diff/semantic-projections';
import {
    agentNodeWithTasks,
    fieldChange,
    liveNodeOfType,
    openPanelOnChangesTab,
    respond,
    scheduleNodeWith,
    SHOWN_DIFF_MARKS,
} from './node-panel-diff.testing';

// Drift guard: every field the version diff compares has a mark in its node's panel, so a changed node never opens a
// panel that shows nothing of what a restore changes. A field added to a projection (`semantic-projections.ts`)
// without a mark in its panel fails here. For each field the panel is opened on the Changes tab with only that
// field changed, narrow and widened (some panels lay out other content when widened); it must then show a mark of
// some kind (a field mark, an Input List, Key-Value or task row, a note under a list, a code diff). The items of a
// keyed collection (Agent tasks, decision table groups) are changed one field at a time, as the diff reports them,
// and also added and removed whole.
// A panel shows some fields only for some values of another (a one-time schedule hides its repeat settings). The
// guard opens such a field with a version that shows it. The Schedule projection drops what the scheduler ignores (the
// repeat and end settings of a one-time run, the end value of another end type, weekdays outside "days" and "weeks"),
// so a hidden field only differs when the field that hides it differs too, and that one is marked.
// Known limit: the scheduler reads weekdays on a "days" schedule, but the panel shows them for "weeks" only, so a
// restore that changes only those weekdays shows no mark in the panel (the canvas badge still says "changed").

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
 * Panels whose field marks come in a later step of this feature (the decision tables with their grids). This list must
 * be empty once that step is done.
 */
const MARKS_PENDING: readonly NodeType[] = [NodeType.TABLE, NodeType.CLASSIFICATION_TABLE];

/**
 * The version node a panel is opened with, where the live graph fixture's node hides fields: it must show every field
 * and hold an item of every keyed collection. Not set: the fixture's node.
 */
const VERSION_NODES: Partial<Record<NodeType, () => NodeModel>> = {
    [NodeType.AGENT]: () => agentNodeWithTasks(),
    [NodeType.SCHEDULE_TRIGGER]: () => scheduleNodeWith({ intervalUnit: 'weeks', weekdays: ['mon', 'wed'] }),
};

/** Fields a panel shows only for some values of another field, each with a version node that shows it. */
const FIELD_VERSION_NODES: Partial<Record<NodeType, Partial<Record<FieldName, () => NodeModel>>>> = {
    [NodeType.SCHEDULE_TRIGGER]: {
        max_runs: () => scheduleNodeWith({ endType: 'after_n_runs', endDateTime: null, maxRuns: 5 }),
    },
};

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

/** One change the guard opens a panel with: a restore makes it alone. */
interface GuardCase {
    /** The field as the diff names it (`tasks[].name`), and as `NO_MARK_ON_PURPOSE` lists it. */
    field: FieldName;
    /** What changes, for the test name. */
    name: string;
    /** The version node the panel shows. */
    node: NodeModel;
    change: FieldChange;
}

/**
 * A change of every field the version diff compares for the node type, as the diff reports it: a nested field by each
 * of its parts, a keyed collection by each field of an item and by an item a restore adds or removes.
 */
function guardCasesOf(type: NodeType): GuardCase[] {
    const node = VERSION_NODES[type]?.() ?? liveNodeOfType(type);
    return Object.entries(projectionOf(type, node)).flatMap(([top, value]): GuardCase[] => {
        const field = top as FieldName;
        const keyPrefix = keyPrefixOf(field);
        if (keyPrefix !== undefined) return itemCases(field, keyPrefix, value as Record<string, unknown>, node);
        if (isNestedField(field) && value !== null && typeof value === 'object') {
            return Object.keys(value).map((part) => wholeFieldCase(type, `${field}.${part}` as FieldName, node));
        }
        return [wholeFieldCase(type, field, node)];
    });
}

/** A change of `field` alone: the version holds the node's value, the canvas another of the same shape. */
function wholeFieldCase(type: NodeType, field: FieldName, defaultNode: NodeModel): GuardCase {
    const node = FIELD_VERSION_NODES[type]?.[field]?.() ?? defaultNode;
    const version = versionValueOf(type, field, node);
    return { field, name: field, node, change: fieldChange(field, otherValueThan(version), version) };
}

/**
 * The changes of the first item of a keyed collection, one field at a time, the item added by a restore, and an item
 * only the canvas has (removed by a restore). The canvas-only item takes the next free key: the next position for
 * tasks, a new name for groups.
 */
function itemCases(
    collection: FieldName,
    keyPrefix: string,
    items: Record<string, unknown>,
    node: NodeModel
): GuardCase[] {
    const keys = Object.keys(items);
    const itemField = `${collection}[]` as FieldName;
    const itemPath = (key: string): string => `${collection}[${keyPrefix}${key}]`;
    const canvasOnlyKey = keys.every((key) => /^\d+$/.test(key)) ? String(keys.length + 1) : 'canvas only';
    const firstKey = keys[0];
    const firstItem = firstKey === undefined ? { canvas_only: 'canvas item' } : items[firstKey];
    const removed: GuardCase = {
        field: itemField,
        name: `${itemField} removed by a restore`,
        node,
        change: {
            path: itemPath(canvasOnlyKey),
            field: itemField,
            status: 'deleted',
            current: firstItem,
            version: null,
        },
    };
    if (firstKey === undefined) return [removed];
    const added: GuardCase = {
        field: itemField,
        name: `${itemField} added by a restore`,
        node,
        change: { path: itemPath(firstKey), field: itemField, status: 'added', current: null, version: firstItem },
    };
    const itemFields = Object.entries(firstItem as Record<string, unknown>).map(([part, version]): GuardCase => {
        const field = `${itemField}.${part}` as FieldName;
        return {
            field,
            name: field,
            node,
            change: {
                path: `${itemPath(firstKey)}.${part}`,
                field,
                status: 'changed',
                current: otherValueThan(version),
                version,
            },
        };
    });
    return [...itemFields, added, removed];
}

/** The cases of the type whose field must have a mark (the ones not left without one on purpose). */
function casesToMarkOf(type: NodeType): GuardCase[] {
    return guardCasesOf(type).filter(({ field }) => !Object.hasOwn(NO_MARK_ON_PURPOSE[type] ?? {}, field));
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
            const diffed = guardCasesOf(type as NodeType).map(({ field }) => field);
            for (const field of Object.keys(fields ?? {})) {
                expect(
                    diffed,
                    `${field} is not a diffed field of ${type}: remove it from NO_MARK_ON_PURPOSE`
                ).toContain(field);
            }
        }
    });

    it.each(GUARDED_TYPES)(
        'opens %s with an item of each keyed collection, so their item fields are checked',
        (type) => {
            const collections = guardCasesOf(type)
                .filter(({ change }) => change.status === 'deleted')
                .map(({ field }) => field);

            for (const collection of collections) {
                expect(
                    guardCasesOf(type).some(({ field, change }) => field === collection && change.status === 'added'),
                    `${type}: give VERSION_NODES a version node with an item of ${collection}`
                ).toBe(true);
            }
        }
    );

    const CASES = GUARDED_TYPES.flatMap((type) =>
        casesToMarkOf(type).flatMap((guardCase) =>
            LAYOUTS.map(({ layout, expanded }) => ({
                type,
                ...guardCase,
                layout,
                expanded,
                panel: PANEL_COMPONENT_MAP[type].name.replace(/^_/, ''),
            }))
        )
    );

    it.each(CASES)(
        '$type panel, $layout, marks a change of $name',
        ({ type, name, node, change, layout, expanded, panel }) => {
            expect(
                shownMarkCount(type, node, change, expanded),
                `${panel} (${layout}) shows nothing when a restore changes ${name}: wrap the field in ` +
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
        const allMarked = casesToMarkOf(type).every(({ node, change }) =>
            LAYOUTS.every(({ expanded }) => shownMarkCount(type, node, change, expanded) > 0)
        );

        expect(allMarked, `Every diffed field of the ${type} panel is marked: remove ${type} from MARKS_PENDING`).toBe(
            false
        );
    });
});
