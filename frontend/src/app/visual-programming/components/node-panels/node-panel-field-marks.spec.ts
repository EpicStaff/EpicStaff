import { Type } from '@angular/core';
import { ComponentFixture } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { KeyValueNodeModel } from '../../core/models/node.model';
import { FieldChange } from '../../utils/diff';
import { shownCodeDiffLanguages, shownCodeDiffs } from '../code-diff-view/code-diff-view.testing';
import { AudioToTextNodePanelComponent } from './audio-to-text-node-panel/audio-to-text-node-panel.component';
import { EndNodePanelComponent } from './end-node-panel/end-node-panel.component';
import { FileExtractorNodePanelComponent } from './file-extractor-node-panel/file-extractor-node-panel.component';
import { KeyValueNodePanelComponent } from './key-value-node-panel/key-value-node-panel.component';
import { KnowledgeRetrieverNodePanelComponent } from './knowledge-retriever-node-panel/knowledge-retriever-node-panel.component';
import {
    ChangesTabOptions,
    fieldChange,
    hoverTooltip,
    liveNodeOfType,
    markedFields,
    openPanelOnChangesTab,
    respond,
    SHOWN_DIFF_MARKS,
} from './node-panel-diff.testing';
import { SubGraphNodePanelComponent } from './subgraph-node-panel/subgraph-node-panel.component';
import { TelegramTriggerNodePanelComponent } from './telegram-trigger-node-panel/telegram-trigger-node-panel.component';
import { WebhookTriggerNodePanelComponent } from './webhook-trigger-node-panel/webhook-trigger-node-panel.component';

// The panels of the simple node types on the Changes tab of a version preview: each field a restore changes is
// marked on its value, and nothing else is. The panels show the version (the live graph fixture's nodes); the
// changes say what the canvas holds now.

interface Panel {
    name: string;
    component: Type<unknown>;
    type: NodeType;
    /** What the panel needs from the backend to show the version's values (the options it loads). */
    load?: () => void;
}

const FILE_EXTRACTOR: Panel = {
    name: 'File extractor',
    component: FileExtractorNodePanelComponent,
    type: NodeType.FILE_EXTRACTOR,
};
const AUDIO: Panel = { name: 'Audio to text', component: AudioToTextNodePanelComponent, type: NodeType.AUDIO_TO_TEXT };
const SUBFLOW: Panel = {
    name: 'Subflow',
    component: SubGraphNodePanelComponent,
    type: NodeType.SUBGRAPH,
    load: () =>
        respond('graph-light/', {
            count: 2,
            next: null,
            previous: null,
            results: [
                { id: 99, name: 'Billing' },
                { id: 12, name: 'Refunds' },
            ],
        }),
};
const WEBHOOK: Panel = {
    name: 'Webhook',
    component: WebhookTriggerNodePanelComponent,
    type: NodeType.WEBHOOK_TRIGGER,
    load: () =>
        respond('webhook-triggers/', {
            results: [
                { id: 77, provider_type: 'ngrok', ngrok_config: { name: 'orders-hook' } },
                { id: 5, provider_type: 'ngrok', ngrok_config: { name: 'old-hook' } },
            ],
        }),
};
const TELEGRAM: Panel = {
    name: 'Telegram',
    component: TelegramTriggerNodePanelComponent,
    type: NodeType.TELEGRAM_TRIGGER,
    load: () => {
        respond('secrets/', {
            count: 2,
            next: null,
            results: [
                { id: 102, name: 'BOT_TOKEN', tail: 'abcd' },
                { id: 103, name: 'OLD_BOT_TOKEN', tail: 'efgh' },
            ],
        });
        respond('secrets/recycle-bin/', { count: 0, next: null, results: [] });
    },
};
const KNOWLEDGE: Panel = {
    name: 'Knowledge',
    component: KnowledgeRetrieverNodePanelComponent,
    type: NodeType.KNOWLEDGE_RETRIEVER,
    load: () => {
        respond('source-collections/', [
            { collection_id: 5, collection_name: 'Manuals' },
            { collection_id: 6, collection_name: 'Contracts' },
        ]);
        respond('source-collections/5/available-rags/', [
            { rag_id: 8, rag_type: 'naive', rag_status: 'completed', collection_id: 5 },
            { rag_id: 9, rag_type: 'graph', rag_status: 'completed', collection_id: 5 },
        ]);
    },
};
const KEY_VALUE: Panel = {
    name: 'Key-Value',
    component: KeyValueNodePanelComponent,
    type: NodeType.KEY_VALUE,
    load: () =>
        respond('key-value-tables/', {
            count: 2,
            next: null,
            previous: null,
            results: [
                { id: 61, name: 'customers' },
                { id: 62, name: 'orders' },
            ],
        }),
};
const END: Panel = { name: 'End', component: EndNodePanelComponent, type: NodeType.END };

let fixture: ComponentFixture<unknown>;

afterEach(() => fixture?.destroy());

function open(panel: Panel, fields: FieldChange[], options: ChangesTabOptions = {}): HTMLElement {
    fixture = openPanelOnChangesTab(panel.component, liveNodeOfType(panel.type), fields, options);
    panel.load?.();
    fixture.detectChanges();
    return fixture.nativeElement;
}

/** A field change, the element its mark wraps (form control or element), and the tooltip it shows. */
interface FieldCase {
    panel: Panel;
    change: FieldChange;
    marked: string;
    tooltip: string;
}

const NAME_CHANGE = fieldChange('node_name', 'Old name', 'New name');
const OUTPUT_PATH_CHANGE = fieldChange('output_variable_path', 'variables.old', null);

const FIELD_CASES: FieldCase[] = [
    ...[FILE_EXTRACTOR, AUDIO, SUBFLOW, KNOWLEDGE].flatMap((panel): FieldCase[] => [
        { panel, change: NAME_CHANGE, marked: 'node_name', tooltip: '[Old] name' },
        { panel, change: OUTPUT_PATH_CHANGE, marked: 'output_variable_path', tooltip: '[variables.old]' },
    ]),
    { panel: SUBFLOW, change: fieldChange('subgraph', 12, 99), marked: 'selectedFlowId', tooltip: '[Refunds]' },
    // A flow the list does not hold (deleted, or the flow itself) shows by id, as the missing-reference notes do.
    { panel: SUBFLOW, change: fieldChange('subgraph', 41, 99), marked: 'selectedFlowId', tooltip: '[flow #41]' },
    { panel: WEBHOOK, change: NAME_CHANGE, marked: 'node_name', tooltip: '[Old] name' },
    {
        panel: WEBHOOK,
        change: fieldChange('python_code.libraries', ['requests'], []),
        marked: 'libraries',
        tooltip: '[requests]',
    },
    {
        panel: WEBHOOK,
        change: fieldChange('python_code.secret_names', ['DB_PASS'], []),
        marked: 'app-node-secrets-field',
        tooltip: '[DB_PASS]',
    },
    {
        panel: WEBHOOK,
        change: fieldChange('python_code.execution_timeout', 90, null),
        marked: 'app-execution-timeout-field',
        tooltip: '[00:01:30]',
    },
    {
        panel: WEBHOOK,
        change: fieldChange('use_storage', true, false),
        marked: 'app-node-storage-section',
        tooltip: '[on]',
    },
    {
        panel: WEBHOOK,
        change: fieldChange('webhook_trigger', 5, 77),
        marked: 'webhook_trigger',
        tooltip: '[old-hook (ngrok)]',
    },
    {
        panel: WEBHOOK,
        change: fieldChange('webhook_trigger', 8, 77),
        marked: 'webhook_trigger',
        tooltip: '[trigger #8]',
    },
    { panel: TELEGRAM, change: NAME_CHANGE, marked: 'node_name', tooltip: '[Old] name' },
    {
        panel: TELEGRAM,
        change: fieldChange('telegram_bot_api_key_secret_id', 103, 102),
        marked: 'telegram_bot_api_key_secret_id',
        tooltip: '[OLD_BOT_TOKEN]',
    },
    {
        panel: TELEGRAM,
        change: fieldChange('telegram_bot_api_key_secret_id', 104, 102),
        marked: 'telegram_bot_api_key_secret_id',
        tooltip: '[secret #104]',
    },
    {
        panel: TELEGRAM,
        change: fieldChange('webhook_trigger', 8, null),
        marked: 'webhook_trigger',
        tooltip: '[trigger #8]',
    },
    // One mark on the whole list: the fields a restore removes are struck.
    {
        panel: TELEGRAM,
        change: fieldChange(
            'fields',
            [
                { parent: 'message', field_name: 'chat', variable_path: 'variables.chat' },
                { parent: 'message', field_name: 'text', variable_path: 'variables.text' },
            ],
            [{ parent: 'message', field_name: 'text', variable_path: 'variables.text' }]
        ),
        marked: 'div.output-fields__container',
        tooltip: '[message.chat (variables.chat)], message.text (variables.text)',
    },
    {
        panel: KNOWLEDGE,
        change: fieldChange('source_collection', 6, 5),
        marked: 'knowledge_collection',
        tooltip: '[Contracts]',
    },
    // The RAG select shows a RAG by its type; one it does not list gets its id too.
    { panel: KNOWLEDGE, change: fieldChange('rag_type', 'graph', 'naive'), marked: 'rag', tooltip: '[graph (RAG #8)]' },
    { panel: KNOWLEDGE, change: fieldChange('rag_id', 10, 8), marked: 'rag', tooltip: '[naive (RAG #10)]' },
    {
        panel: KNOWLEDGE,
        change: fieldChange('query', 'find the old docs', 'q'),
        marked: 'query',
        tooltip: '[find the old docs]',
    },
    { panel: KEY_VALUE, change: NAME_CHANGE, marked: 'node_name', tooltip: '[Old] name' },
    {
        panel: KEY_VALUE,
        change: fieldChange('key_value_table', 62, 61),
        marked: 'app-select-dropdown',
        tooltip: '[orders]',
    },
    {
        panel: KEY_VALUE,
        change: fieldChange('key_value_table', 63, 61),
        marked: 'app-select-dropdown',
        tooltip: '[table #63]',
    },
    { panel: KEY_VALUE, change: fieldChange('mode', 'delete', 'write'), marked: 'mode', tooltip: '[Delete]' },
];

describe('Node panels of simple node types on the Changes tab of a version preview', () => {
    it.each(FIELD_CASES)(
        '$panel.name: marks $change.field, and only it, when a restore changes it',
        ({ panel, change, marked }) => {
            expect(markedFields(open(panel, [change]))).toEqual([marked]);
        }
    );

    it.each(FIELD_CASES)(
        '$panel.name: shows the current $change.field in the tooltip as the field shows it ($tooltip)',
        ({ panel, change, marked, tooltip }) => {
            open(panel, [change]);

            expect(hoverTooltip(fixture, `[formcontrolname="${marked}"], ${marked.replace('div.', '.')}`)).toBe(
                tooltip
            );
        }
    );

    const PANELS = [FILE_EXTRACTOR, AUDIO, SUBFLOW, WEBHOOK, TELEGRAM, KNOWLEDGE, KEY_VALUE, END];
    const EVERY_CHANGE = FIELD_CASES.map(({ change }) => change);

    it.each(
        PANELS.flatMap((panel) => [
            { panel, case: 'off the Changes tab (Preview tab, live editor)', options: { onChangesTab: false } },
            { panel, case: 'on a node a restore adds', options: { status: 'added' as const } },
            { panel, case: 'on a node a restore removes', options: { status: 'deleted' as const } },
        ])
    )('$panel.name: shows no mark $case', ({ panel, options }) => {
        const root = open(panel, [...EVERY_CHANGE, ...ROW_CHANGES, OUTPUT_MAP_CHANGE], options);

        expect(root.querySelectorAll(SHOWN_DIFF_MARKS)).toHaveLength(0);
        expect(root.querySelector('.diff-value-marked')).toBeNull();
    });

    it.each(PANELS)('$name: shows no mark without a field change', (panel) => {
        const root = open(panel, []);

        expect(root.querySelectorAll(SHOWN_DIFF_MARKS)).toHaveLength(0);
    });
});

const INPUT_MAP_CHANGE = fieldChange('input_map', { gone: 'variables.gone' }, {});
const ENTRIES_CHANGE = fieldChange('entries', [], [{ key: 'customer', value: 'variables.customer' }]);
const ROW_CHANGES = [INPUT_MAP_CHANGE, ENTRIES_CHANGE];
const OUTPUT_MAP_CHANGE = fieldChange('output_map', { answer: 'b' }, { answer: 'a' });

/** Each Input List row: its cells' text, and whether it shows a diff status. */
function inputListRows(root: HTMLElement): [string, boolean][] {
    return Array.from(root.querySelectorAll<HTMLElement>('.readonly-row'), (row) => [
        Array.from(row.querySelectorAll('.readonly-cell'), (cell) =>
            cell.textContent?.replace(/\s+/g, ' ').trim()
        ).join(' '),
        row.classList.contains('diff-field-mark--shown') || row.classList.contains('readonly-row--removed'),
    ]);
}

describe('The Input List of a simple node panel on the Changes tab', () => {
    it.each([FILE_EXTRACTOR, AUDIO, SUBFLOW, KNOWLEDGE])('$name: marks the rows a restore changes', (panel) => {
        const root = open(panel, [
            fieldChange('input_map', { user: 'variables.user', gone: 'variables.gone' }, { user: 'variables.account' }),
        ]);

        expect(markedFields(root)).toEqual([]);
        expect(inputListRows(root)).toContainEqual(['Restore removes this input: gone variables.gone', true]);
    });
});

describe('Knowledge panel RAG on the Changes tab', () => {
    it('shows a RAG the select lists by its type only', () => {
        open(KNOWLEDGE, [fieldChange('rag_type', 'graph', 'naive'), fieldChange('rag_id', 9, 8)]);

        expect(markedFields(fixture.nativeElement)).toEqual(['rag']);
        expect(hoverTooltip(fixture, '[formcontrolname="rag"]')).toBe('[graph]');
    });
});

describe('Knowledge panel search settings on the Changes tab', () => {
    const CONFIGS_CHANGE = fieldChange(
        'search_configs',
        { naive: { search_limit: 5, similarity_threshold: 0.7, is_suggested: false } },
        { naive: { search_limit: 3, similarity_threshold: 0.7, is_suggested: false } }
    );

    it.each([
        { case: 'the settings', change: CONFIGS_CHANGE },
        { case: 'the search method', change: fieldChange('search_method', 'local', null) },
    ])('boxes the whole section, its inputs left as they are, when a restore changes $case', ({ change }) => {
        const root = open(KNOWLEDGE, [change]);

        const marks = root.querySelectorAll('app-diff-field-mark.diff-field-mark--shown');
        expect(marks).toHaveLength(1);
        expect(marks[0].classList).toContain('diff-field-mark--group');
        expect(marks[0].querySelector('.search-config-section app-rag-tab')).not.toBeNull();
        expect(root.querySelector('.diff-value-marked')).toBeNull();
    });

    it('shows the current settings in the tooltip, the part a restore replaces struck', () => {
        open(KNOWLEDGE, [CONFIGS_CHANGE]);

        expect(hoverTooltip(fixture, '.search-config-section')).toContain('"search_limit":[5]');
    });
});

describe('Knowledge panel query in the widened panel', () => {
    it('marks the query editor, whose frame and badge sit on the editor column', () => {
        const root = open(KNOWLEDGE, [fieldChange('query', 'old', 'q')], { expanded: true });

        expect(markedFields(root)).toEqual(['query']);
        const mark = root.querySelector('app-diff-field-mark.diff-field-mark--shown')!;
        expect(mark.classList).toContain('query-mark');
        expect(mark.classList).toContain('diff-field-mark--draws-badge');
    });
});

describe('Key-Value entries on the Changes tab', () => {
    const KEY_VALUE_NODE = liveNodeOfType(NodeType.KEY_VALUE) as KeyValueNodeModel;
    const VERSION_ENTRIES = [
        { key: 'customer', value: 'variables.customer' },
        { key: 'order', value: 'variables.order' },
        { key: 'kept', value: 'variables.kept' },
    ];

    function openEntries(current: unknown[]): HTMLElement {
        fixture = openPanelOnChangesTab(
            KeyValueNodePanelComponent,
            { ...KEY_VALUE_NODE, data: { ...KEY_VALUE_NODE.data, entries: VERSION_ENTRIES } },
            [fieldChange('entries', current, VERSION_ENTRIES)]
        );
        return fixture.nativeElement;
    }

    /** Each entry row: what a screen reader reads first, its fields, and how it is marked. */
    function entryRows(root: HTMLElement): { status: string; text: string }[] {
        return Array.from(root.querySelectorAll<HTMLElement>('.entry-row-mark'), (row) => ({
            status: row.classList.contains('diff-field-mark--shown')
                ? 'changed'
                : row.classList.contains('entry-row-mark--added')
                  ? 'added'
                  : row.classList.contains('entry-row-mark--removed')
                    ? 'removed'
                    : 'kept',
            text: [
                row.querySelector('.visually-hidden')?.textContent?.trim() ?? '',
                ...Array.from(row.querySelectorAll<HTMLElement>('input.entry-input, .entry-input--removed'), (field) =>
                    field instanceof HTMLInputElement ? field.value : field.textContent?.trim()
                ),
            ]
                .filter((part) => part)
                .join(' '),
        }));
    }

    it('pairs the rows with the canvas by key: changed, added, kept, and a row only the canvas has', () => {
        const root = openEntries([
            { key: 'kept', value: 'variables.kept' },
            { key: 'customer', value: 'variables.client' },
            { key: 'gone', value: 'variables.gone' },
        ]);

        // Write mode: the key, then the variable it stores.
        expect(entryRows(root)).toEqual([
            { status: 'changed', text: 'customer variables.customer' },
            { status: 'added', text: 'Restore adds this key: order variables.order' },
            { status: 'kept', text: 'kept variables.kept' },
            { status: 'removed', text: 'Restore removes this key: gone variables.gone' },
        ]);
        expect(markedFields(root)).toEqual([]);
    });

    it('shows the canvas variable path of a changed row in its tooltip', () => {
        const root = openEntries([{ key: 'customer', value: 'variables.client' }, ...VERSION_ENTRIES.slice(1)]);

        root.querySelector('.entry-row-mark.diff-field-mark--shown')!.dispatchEvent(new Event('mouseenter'));
        fixture.detectChanges();

        expect(document.querySelector('.diff-field-mark__tooltip-value')?.textContent?.replace(/\s+/g, '')).toBe(
            'variables.client'
        );
    });

    const ORDER_NOTE = 'Restore changes the order of the entries.';
    const orderNotes = (root: HTMLElement): string[] =>
        Array.from(root.querySelectorAll('.entry-order-note'), (note) => note.textContent?.trim() ?? '');

    it('says a restore reorders the entries when the rows only move, which no row mark shows', () => {
        const root = openEntries([...VERSION_ENTRIES].reverse());

        expect(entryRows(root).map((row) => row.status)).toEqual(['kept', 'kept', 'kept']);
        expect(orderNotes(root)).toEqual([ORDER_NOTE]);
    });

    it('says a restore reorders the entries when rows change too', () => {
        const root = openEntries([
            { key: 'kept', value: 'variables.kept' },
            { key: 'customer', value: 'variables.client' },
        ]);

        expect(entryRows(root).map((row) => row.status)).toEqual(['changed', 'added', 'kept']);
        expect(orderNotes(root)).toEqual([ORDER_NOTE]);
    });

    it('has no order note when the shared rows keep their order', () => {
        const root = openEntries([
            { key: 'customer', value: 'variables.client' },
            { key: 'kept', value: 'variables.kept' },
        ]);

        expect(orderNotes(root)).toEqual([]);
    });

    it.each<{ case: string; options: ChangesTabOptions }>([
        { case: 'off the Changes tab', options: { onChangesTab: false } },
        { case: 'on a node a restore adds', options: { status: 'added' } },
    ])('has no order note $case', ({ options }) => {
        fixture = openPanelOnChangesTab(
            KeyValueNodePanelComponent,
            { ...KEY_VALUE_NODE, data: { ...KEY_VALUE_NODE.data, entries: VERSION_ENTRIES } },
            [fieldChange('entries', [...VERSION_ENTRIES].reverse(), VERSION_ENTRIES)],
            options
        );

        expect(orderNotes(fixture.nativeElement)).toEqual([]);
    });

    it.each([
        { case: 'without an entries change', fields: [] },
        { case: 'when only the mode changes', fields: [fieldChange('mode', 'read', 'write')] },
    ])('marks no row $case', ({ fields }) => {
        fixture = openPanelOnChangesTab(KeyValueNodePanelComponent, KEY_VALUE_NODE, fields);

        expect(
            (fixture.nativeElement as HTMLElement).querySelectorAll(
                '.entry-row-mark.diff-field-mark--shown, .entry-row-mark--added, .entry-row-mark--removed'
            )
        ).toHaveLength(0);
    });
});

describe('End panel output map on the Changes tab', () => {
    it('marks the JSON editor of the narrow panel with the expand hint, not the JSON', () => {
        const root = open(END, [OUTPUT_MAP_CHANGE]);

        expect(markedFields(root)).toEqual(['app-json-editor']);
        const mark = root.querySelector('app-diff-field-mark.diff-field-mark--shown')!;
        expect(document.getElementById(mark.getAttribute('aria-describedby') ?? '')?.textContent).toBe(
            'Expand the panel to see the changes.'
        );
        expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
    });

    it('shows a JSON diff of the current canvas and the version output map in the widened panel', () => {
        const root = open(END, [OUTPUT_MAP_CHANGE], { expanded: true });

        expect(shownCodeDiffs(fixture.debugElement)).toEqual([
            { current: '{\n  "answer": "b"\n}', version: '{\n  "answer": "a"\n}' },
        ]);
        expect(shownCodeDiffLanguages(fixture.debugElement)).toEqual(['json']);
        expect(root.querySelector('app-json-editor')).toBeNull();
        expect(markedFields(root)).toEqual([]);
    });

    it.each([
        { case: 'the output map is unchanged', fields: [] as FieldChange[], options: {} },
        { case: 'the node is added', fields: [OUTPUT_MAP_CHANGE], options: { status: 'added' as const } },
        { case: 'off the Changes tab', fields: [OUTPUT_MAP_CHANGE], options: { onChangesTab: false } },
    ])('keeps the normal editor in the widened panel when $case', ({ fields, options }) => {
        const root = open(END, fields, { ...options, expanded: true });

        expect(root.querySelector('app-json-editor')).not.toBeNull();
        expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
    });
});

/**
 * Where each newly marked form component draws its mark: the value box gets the border and the badge, the label stays
 * outside. jsdom does not resolve the border colour (a CSS variable), so the styles that only the mark gives show which
 * element is marked: the badge's anchor (`position: relative`) and, for a value shown as plain text, the box drawn
 * around it (its padding).
 */
describe('The value box each newly marked form component draws its mark on', () => {
    type BoxStyle = 'position' | 'paddingTop';
    const READ_ONLY_TEXT_BOX = { marked: { paddingTop: '8px' }, plain: { paddingTop: '0' } };
    const BOXES: {
        panel: Panel;
        change: FieldChange;
        box: string;
        label: string | null;
        marked: Partial<Record<BoxStyle, string>>;
        plain: Partial<Record<BoxStyle, string>>;
    }[] = [
        {
            panel: SUBFLOW,
            change: fieldChange('subgraph', 12, 99),
            box: '.selector__readonly-value',
            label: null,
            ...READ_ONLY_TEXT_BOX,
        },
        {
            panel: TELEGRAM,
            change: fieldChange('telegram_bot_api_key_secret_id', 103, 102),
            box: '.selector__readonly-value',
            label: 'app-tooltip',
            ...READ_ONLY_TEXT_BOX,
        },
        {
            panel: WEBHOOK,
            change: fieldChange('webhook_trigger', 5, 77),
            box: '.wts__trigger',
            label: 'app-tooltip',
            // Read-only, the trigger keeps only its top and bottom padding, the button's.
            marked: { paddingTop: '8px' },
            plain: { paddingTop: '12px' },
        },
        {
            panel: KEY_VALUE,
            change: fieldChange('key_value_table', 62, 61),
            box: '.dropdown-trigger',
            label: null,
            marked: { paddingTop: '8px', position: 'relative' },
            plain: { paddingTop: '0px' },
        },
        {
            panel: TELEGRAM,
            change: fieldChange('fields', [], [{ parent: 'message', field_name: 'text', variable_path: 'v' }]),
            box: '.output-fields__container',
            label: null,
            marked: { position: 'relative' },
            plain: { position: 'static' },
        },
    ];
    const stylesOf = (element: Element, expected: Partial<Record<BoxStyle, string>>) =>
        Object.fromEntries(Object.keys(expected).map((name) => [name, getComputedStyle(element)[name as BoxStyle]]));

    it.each(BOXES)('$panel.name $change.field: on $box', ({ panel, change, box, label, marked }) => {
        const mark = open(panel, [change]).querySelector('app-diff-field-mark.diff-field-mark--shown')!;
        const valueBox = mark.querySelector(box)!;

        expect(stylesOf(valueBox, marked)).toEqual(marked);
        if (label) expect(valueBox.contains(mark.querySelector(label))).toBe(false);
    });

    it.each(BOXES)('$panel.name: leaves $box as it is without a change', ({ panel, box, plain }) => {
        const valueBox = open(panel, []).querySelector(box)!;

        expect(stylesOf(valueBox, plain)).toEqual(plain);
    });

    // An editor clips what sticks out: it draws only a frame, and the mark around it draws the badge.
    it.each([
        { panel: KNOWLEDGE, change: fieldChange('query', 'old', 'q'), editor: 'app-template-textarea' },
        { panel: END, change: OUTPUT_MAP_CHANGE, editor: 'app-json-editor' },
    ])('$panel.name $change.field: a frame inside $editor, the badge on the mark', ({ panel, change, editor }) => {
        const mark = open(panel, [change]).querySelector('app-diff-field-mark.diff-field-mark--shown')!;

        expect(mark.classList).toContain('diff-field-mark--draws-badge');
        expect(mark.firstElementChild?.matches(editor)).toBe(true);
    });
});
