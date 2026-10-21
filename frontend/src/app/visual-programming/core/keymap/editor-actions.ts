import { NodeType } from '@shared/models';

import { MenuNodeType, NODE_MENU_LABELS } from '../constants/node-menu-groups';
import { KeyChord } from './key-chord.util';

export type EditorActionSection = 'Nodes' | 'Editing' | 'Navigating' | 'Selection' | 'Zoom';

export type EditorActionParam = 'flow';

export const ARROW_KEYS = 'ArrowKeys';

export const UP_DOWN_KEYS = 'UpDownKeys';

export interface CanvasPan {
    readonly x: -1 | 0 | 1;
    readonly y: -1 | 0 | 1;
    readonly fast: boolean;
}

export interface EditorAction<Id extends string = EditorActionId> {
    readonly id: Id;
    readonly label: string;
    readonly section: EditorActionSection;
    readonly defaultChords: readonly KeyChord[];
    readonly displayKeys?: readonly string[];
    readonly customizable: boolean;
    readonly nodeType?: MenuNodeType | NodeType.SUBGRAPH;
    readonly param?: EditorActionParam;
    readonly pan?: CanvasPan;
    readonly listed?: false;
}

function panAction<const Id extends `navigating.pan-${string}`>(id: Id, chord: KeyChord, pan: CanvasPan) {
    return {
        id,
        label: 'Move canvas',
        section: 'Navigating',
        defaultChords: [chord],
        customizable: false,
        pan,
        listed: false,
    } as const satisfies EditorAction<Id>;
}

function nodeAction<const Id extends `node.${string}`>(id: Id, nodeType: MenuNodeType, chord: KeyChord) {
    return {
        id,
        label: NODE_MENU_LABELS[nodeType],
        section: 'Nodes',
        defaultChords: [chord],
        customizable: true,
        nodeType,
    } as const satisfies EditorAction<Id>;
}

export const EDITOR_ACTIONS = [
    nodeAction('node.python', NodeType.PYTHON, 'Shift+KeyP'),
    nodeAction('node.classification-table', NodeType.CLASSIFICATION_TABLE, 'Shift+KeyC'),
    nodeAction('node.knowledge-retriever', NodeType.KNOWLEDGE_RETRIEVER, 'Shift+KeyK'),
    nodeAction('node.task', NodeType.TASK, 'Shift+KeyT'),
    nodeAction('node.agent', NodeType.AGENT, 'Shift+KeyA'),
    nodeAction('node.key-value', NodeType.KEY_VALUE, 'Shift+KeyV'),
    nodeAction('node.note', NodeType.NOTE, 'Shift+KeyN'),
    nodeAction('node.decision-table', NodeType.TABLE, 'Shift+KeyD'),
    nodeAction('node.file-extractor', NodeType.FILE_EXTRACTOR, 'Shift+KeyF'),
    nodeAction('node.schedule-trigger', NodeType.SCHEDULE_TRIGGER, 'Shift+KeyS'),
    nodeAction('node.webhook-trigger', NodeType.WEBHOOK_TRIGGER, 'Shift+KeyW'),
    nodeAction('node.telegram-trigger', NodeType.TELEGRAM_TRIGGER, 'Shift+KeyG'),
    nodeAction('node.audio-to-text', NodeType.AUDIO_TO_TEXT, 'Shift+KeyU'),
    nodeAction('node.end', NodeType.END, 'Shift+KeyE'),
    {
        id: 'node.subgraph',
        label: 'Subgraph',
        section: 'Nodes',
        defaultChords: [],
        customizable: true,
        nodeType: NodeType.SUBGRAPH,
        param: 'flow',
    },
    {
        id: 'editing.save',
        label: 'Save',
        section: 'Editing',
        defaultChords: ['Mod+KeyS'],
        customizable: true,
    },
    {
        id: 'editing.undo',
        label: 'Undo',
        section: 'Editing',
        defaultChords: ['Mod+KeyZ'],
        customizable: true,
    },
    {
        id: 'editing.redo',
        label: 'Redo',
        section: 'Editing',
        defaultChords: ['Mod+Shift+KeyZ', 'Mod+KeyY'],
        customizable: true,
    },
    {
        id: 'editing.copy',
        label: 'Copy',
        section: 'Editing',
        defaultChords: ['Mod+KeyC'],
        customizable: true,
    },
    {
        id: 'editing.paste',
        label: 'Paste',
        section: 'Editing',
        defaultChords: ['Mod+KeyV'],
        customizable: true,
    },
    {
        id: 'editing.delete',
        label: 'Delete',
        section: 'Editing',
        defaultChords: ['Delete', 'Backspace'],
        customizable: true,
    },
    {
        id: 'editing.escape',
        label: 'Close panel / clear selection',
        section: 'Editing',
        defaultChords: ['Escape'],
        customizable: false,
    },
    {
        id: 'navigating.node-search',
        label: 'Node search',
        section: 'Navigating',
        defaultChords: ['Mod+KeyF'],
        customizable: true,
    },
    {
        id: 'navigating.shortcuts',
        label: 'Keyboard shortcuts',
        section: 'Navigating',
        defaultChords: ['Mod+Slash'],
        customizable: true,
    },
    {
        id: 'navigating.move-canvas',
        label: 'Move canvas',
        section: 'Navigating',
        defaultChords: [],
        displayKeys: [ARROW_KEYS],
        customizable: false,
    },
    {
        id: 'navigating.move-canvas-fast',
        label: 'Move canvas faster',
        section: 'Navigating',
        defaultChords: [],
        displayKeys: ['Mod', ARROW_KEYS],
        customizable: false,
    },
    {
        id: 'navigating.switch-page',
        label: 'Previous / next page',
        section: 'Navigating',
        defaultChords: [],
        displayKeys: ['Alt', UP_DOWN_KEYS],
        customizable: false,
    },
    panAction('navigating.pan-left', 'ArrowLeft', { x: -1, y: 0, fast: false }),
    panAction('navigating.pan-right', 'ArrowRight', { x: 1, y: 0, fast: false }),
    panAction('navigating.pan-up', 'ArrowUp', { x: 0, y: -1, fast: false }),
    panAction('navigating.pan-down', 'ArrowDown', { x: 0, y: 1, fast: false }),
    panAction('navigating.pan-left-fast', 'Mod+ArrowLeft', { x: -1, y: 0, fast: true }),
    panAction('navigating.pan-right-fast', 'Mod+ArrowRight', { x: 1, y: 0, fast: true }),
    panAction('navigating.pan-up-fast', 'Mod+ArrowUp', { x: 0, y: -1, fast: true }),
    panAction('navigating.pan-down-fast', 'Mod+ArrowDown', { x: 0, y: 1, fast: true }),
    {
        id: 'navigating.node-menu',
        label: 'Open node create menu',
        section: 'Navigating',
        defaultChords: [],
        displayKeys: ['Right click'],
        customizable: false,
    },
    {
        id: 'selection.toggle',
        label: 'Add/remove selection',
        section: 'Selection',
        defaultChords: [],
        displayKeys: ['Mod', 'click'],
        customizable: false,
    },
    {
        id: 'selection.zone',
        label: 'Zone selection',
        section: 'Selection',
        defaultChords: [],
        displayKeys: ['Shift', 'drag'],
        customizable: false,
    },
    {
        id: 'zoom.in',
        label: 'Zoom in',
        section: 'Zoom',
        defaultChords: [],
        displayKeys: ['Mouse wheel up'],
        customizable: false,
    },
    {
        id: 'zoom.out',
        label: 'Zoom out',
        section: 'Zoom',
        defaultChords: [],
        displayKeys: ['Mouse wheel down'],
        customizable: false,
    },
] as const satisfies readonly EditorAction<string>[];

export type EditorActionId = (typeof EDITOR_ACTIONS)[number]['id'];

export const ACTION_PARAMS: ReadonlyMap<string, EditorActionParam> = new Map(
    EDITOR_ACTIONS.flatMap((action: EditorAction) => (action.param ? [[action.id, action.param] as const] : []))
);
