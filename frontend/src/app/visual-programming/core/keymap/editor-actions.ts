import { NodeType } from '@shared/models';

import { PermissionRequirement } from '../../../services/auth/permissions.service';
import { FLOW_ACTION_PERMISSIONS } from '../constants/flow-action-permissions';
import { MenuNodeType, NODE_MENU_LABELS } from '../constants/node-menu-groups';
import { KeyChord } from './key-chord.util';

export type EditorActionSection = 'Flow actions' | 'Nodes' | 'Editing' | 'Navigating' | 'Selection' | 'Zoom';

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
    /** How the shortcuts list shows the keys, one entry per alternative, when the chords alone would not read well. */
    readonly displayChords?: readonly (readonly string[])[];
    readonly customizable: boolean;
    readonly nodeType?: MenuNodeType | NodeType.SUBGRAPH;
    readonly param?: EditorActionParam;
    readonly pan?: CanvasPan;
    /** Moves the selected nodes; `fast` is the long step. */
    readonly moveSelection?: CanvasPan;
    readonly listed?: false;
    /** The permission its button needs; without it the action is left out of the shortcuts list and picker. */
    readonly requires?: PermissionRequirement;
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

function moveSelectionAction<const Id extends `selection.move-${string}`>(id: Id, chord: KeyChord, move: CanvasPan) {
    return {
        id,
        label: 'Move selected nodes',
        section: 'Selection',
        defaultChords: [chord],
        customizable: false,
        moveSelection: move,
        listed: false,
    } as const satisfies EditorAction<Id>;
}

function flowAction<const Id extends `flow.${string}`>(
    id: Id,
    label: string,
    chord: KeyChord,
    requires?: PermissionRequirement
) {
    return {
        id,
        label,
        section: 'Flow actions',
        defaultChords: [chord],
        customizable: true,
        ...(requires ? { requires } : {}),
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
    flowAction('flow.run', 'Run', 'Mod+Enter', FLOW_ACTION_PERMISSIONS.useFlow),
    flowAction('flow.sessions', 'Sessions', 'Alt+KeyS'),
    flowAction('flow.chat', 'Open / close chat', 'Alt+KeyC'),
    flowAction('flow.curl', 'Get cURL', 'Alt+KeyK', FLOW_ACTION_PERMISSIONS.useFlow),
    flowAction('flow.auto-arrange', 'Auto arrange', 'Alt+KeyL'),
    flowAction('flow.add-files', 'Add files', 'Alt+KeyU', FLOW_ACTION_PERMISSIONS.files),
    flowAction('flow.export-import', 'Export / Import menu', 'Alt+KeyX', FLOW_ACTION_PERMISSIONS.exportImport),
    flowAction('flow.extract-subflow', 'Extract to Subflow', 'Alt+KeyG'),
    flowAction('flow.settings', 'Flow settings', 'Alt+Comma'),
    flowAction('flow.domain', 'Domain', 'Alt+KeyM'),
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
        displayChords: [[ARROW_KEYS]],
        customizable: false,
    },
    {
        id: 'navigating.move-canvas-fast',
        label: 'Move canvas faster',
        section: 'Navigating',
        defaultChords: [],
        displayChords: [['Mod', ARROW_KEYS]],
        customizable: false,
    },
    {
        id: 'navigating.switch-page',
        label: 'Previous / next page',
        section: 'Navigating',
        defaultChords: [],
        displayChords: [['Alt', UP_DOWN_KEYS]],
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
        displayChords: [['Right click']],
        customizable: false,
    },
    {
        id: 'selection.toggle',
        label: 'Add/remove selection',
        section: 'Selection',
        defaultChords: [],
        displayChords: [['Mod', 'click']],
        customizable: false,
    },
    {
        id: 'selection.zone',
        label: 'Zone selection',
        section: 'Selection',
        defaultChords: [],
        displayChords: [['Shift', 'drag']],
        customizable: false,
    },
    {
        id: 'selection.move',
        label: 'Move selected nodes',
        section: 'Selection',
        defaultChords: [],
        displayChords: [[ARROW_KEYS]],
        customizable: false,
    },
    {
        id: 'selection.move-fast',
        label: 'Move selected nodes faster',
        section: 'Selection',
        defaultChords: [],
        displayChords: [['Shift', ARROW_KEYS]],
        customizable: false,
    },
    // The plain arrows belong to the pan actions, which move the selection instead when there is one.
    moveSelectionAction('selection.move-left-fast', 'Shift+ArrowLeft', { x: -1, y: 0, fast: true }),
    moveSelectionAction('selection.move-right-fast', 'Shift+ArrowRight', { x: 1, y: 0, fast: true }),
    moveSelectionAction('selection.move-up-fast', 'Shift+ArrowUp', { x: 0, y: -1, fast: true }),
    moveSelectionAction('selection.move-down-fast', 'Shift+ArrowDown', { x: 0, y: 1, fast: true }),
    {
        id: 'zoom.in',
        label: 'Zoom in',
        section: 'Zoom',
        // Ctrl + "+" needs Shift on a US keyboard but not on a German one, so both are bound.
        defaultChords: ['Mod+Equal', 'Mod+Shift+Equal'],
        displayChords: [['Mod', '+'], ['Mouse wheel up']],
        customizable: false,
    },
    {
        id: 'zoom.out',
        label: 'Zoom out',
        section: 'Zoom',
        defaultChords: ['Mod+Minus'],
        displayChords: [['Mod', '-'], ['Mouse wheel down']],
        customizable: false,
    },
] as const satisfies readonly EditorAction<string>[];

export type EditorActionId = (typeof EDITOR_ACTIONS)[number]['id'];

const OVERRIDABLE_SECTIONS: ReadonlySet<EditorActionSection> = new Set<EditorActionSection>(['Flow actions', 'Nodes']);

// The user can change or clear these keys, and an additional shortcut can take them; other sections keep theirs.
export function isOverridable(action: EditorAction): boolean {
    return action.customizable && OVERRIDABLE_SECTIONS.has(action.section) && action.defaultChords.length > 0;
}

export const ACTION_PARAMS: ReadonlyMap<string, EditorActionParam> = new Map(
    EDITOR_ACTIONS.flatMap((action: EditorAction) => (action.param ? [[action.id, action.param] as const] : []))
);
