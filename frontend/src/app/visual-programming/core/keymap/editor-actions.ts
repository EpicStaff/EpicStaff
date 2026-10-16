import { NodeType } from '@shared/models';

import { MenuNodeType, NODE_MENU_LABELS } from '../constants/node-menu-groups';
import { KeyChord } from './key-chord.util';

export type EditorActionSection = 'Nodes' | 'Editing' | 'Navigating' | 'Selection' | 'Zoom';

export interface EditorAction<Id extends string = EditorActionId> {
    readonly id: Id;
    readonly label: string;
    readonly section: EditorActionSection;
    readonly defaultChords: readonly KeyChord[];
    readonly displayKeys?: readonly string[];
    readonly rebindable: boolean;
    readonly nodeType?: MenuNodeType;
}

function nodeAction<const Id extends `node.${string}`>(id: Id, nodeType: MenuNodeType, chord: KeyChord) {
    return {
        id,
        label: NODE_MENU_LABELS[nodeType],
        section: 'Nodes',
        defaultChords: [chord],
        rebindable: true,
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
    { id: 'editing.save', label: 'Save', section: 'Editing', defaultChords: ['Mod+KeyS'], rebindable: false },
    { id: 'editing.undo', label: 'Undo', section: 'Editing', defaultChords: ['Mod+KeyZ'], rebindable: false },
    {
        id: 'editing.redo',
        label: 'Redo',
        section: 'Editing',
        defaultChords: ['Mod+Shift+KeyZ', 'Mod+KeyY'],
        rebindable: false,
    },
    { id: 'editing.copy', label: 'Copy', section: 'Editing', defaultChords: ['Mod+KeyC'], rebindable: false },
    { id: 'editing.paste', label: 'Paste', section: 'Editing', defaultChords: ['Mod+KeyV'], rebindable: false },
    {
        id: 'editing.delete',
        label: 'Delete',
        section: 'Editing',
        defaultChords: ['Delete', 'Backspace'],
        rebindable: false,
    },
    {
        id: 'editing.escape',
        label: 'Close panel / clear selection',
        section: 'Editing',
        defaultChords: ['Escape'],
        rebindable: false,
    },
    {
        id: 'navigating.node-search',
        label: 'Node search',
        section: 'Navigating',
        defaultChords: ['Mod+KeyF'],
        rebindable: false,
    },
    {
        id: 'navigating.shortcuts',
        label: 'Keyboard shortcuts',
        section: 'Navigating',
        defaultChords: ['Mod+Slash'],
        rebindable: false,
    },
    {
        id: 'navigating.node-menu',
        label: 'Open node create menu',
        section: 'Navigating',
        defaultChords: [],
        displayKeys: ['Right click'],
        rebindable: false,
    },
    {
        id: 'selection.toggle',
        label: 'Add/remove selection',
        section: 'Selection',
        defaultChords: [],
        displayKeys: ['Mod', 'click'],
        rebindable: false,
    },
    {
        id: 'selection.zone',
        label: 'Zone selection',
        section: 'Selection',
        defaultChords: [],
        displayKeys: ['Shift', 'drag'],
        rebindable: false,
    },
    {
        id: 'zoom.in',
        label: 'Zoom in',
        section: 'Zoom',
        defaultChords: [],
        displayKeys: ['Mouse wheel up'],
        rebindable: false,
    },
    {
        id: 'zoom.out',
        label: 'Zoom out',
        section: 'Zoom',
        defaultChords: [],
        displayKeys: ['Mouse wheel down'],
        rebindable: false,
    },
] as const satisfies readonly EditorAction<string>[];

export type EditorActionId = (typeof EDITOR_ACTIONS)[number]['id'];
