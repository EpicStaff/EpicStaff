import type { ShortcutSection } from './components/shortcuts-modal/shortcuts-modal.component';

export const FLOW_SHORTCUT_SECTIONS: ShortcutSection[] = [
    // {
    //     id: 'alignment',
    //     title: 'Alignment',
    //     rows: [
    //         { id: 'align-left', label: 'Align left', keys: ['Alt', 'A'] },
    //         { id: 'align-right', label: 'Align right', keys: ['Alt', 'D'] },
    //         { id: 'align-top', label: 'Align top', keys: ['Alt', 'W'] },
    //         { id: 'align-bottom', label: 'Align bottom', keys: ['Alt', 'S'] },
    //         { id: 'align-center-h', label: 'Align center (horizontally)', keys: ['Alt', 'H'] },
    //         { id: 'align-center-v', label: 'Align center (vertically)', keys: ['Alt', 'V'] },
    //     ],
    // },
    {
        id: 'navigating',
        title: 'Navigating',
        rows: [
            { id: 'next-item', label: 'Go to the next item', keys: ['Tab'] },
            { id: 'prev-item', label: 'Go to the previous item', keys: ['Shift', 'Tab'] },
            { id: 'node-search', label: 'Node search', keys: ['Ctrl', 'F'] },
            // { id: 'first-item', label: 'First item', keys: ['Home'] },
            // { id: 'last-item', label: 'Last item', keys: ['End'] },
            // { id: 'add-element', label: 'Add element', keys: ['N'] },
        ],
    },
    // {
    //     id: 'basic-actions',
    //     title: 'Basic Actions',
    //     rows: [
    //         { id: 'move-items', label: 'Move items', keys: ['arrows'] },
    //         { id: 'fast-move', label: 'Fast move', keys: ['Shift', 'arrows'] },
    //         { id: 'select-all', label: 'Select All', keys: ['Ctrl', 'A'] },
    //         { id: 'duplicate', label: 'Duplicate', keys: ['Ctrl', 'D'] },
    //         { id: 'search', label: 'Search', keys: ['/'] },
    //     ],
    // },
    {
        id: 'selection',
        title: 'Selection',
        rows: [
            // { id: 'select-item', label: 'Select an item', keys: ['Space'] },
            // { id: 'select-several', label: 'Select several items', keys: ['Shift', '←', '→', '↑', '↓'] },
            { id: 'add-remove-selection', label: 'Add/remove selection', keys: ['Ctrl', 'click'] },
            { id: 'zone-selection', label: 'Zone selection', keys: ['Ctrl', 'Shift', 'click'] },
            // { id: 'remove-selection', label: 'Remove all selection', keys: ['Esc'] },
        ],
    },
    // {
    //     id: 'connections',
    //     title: 'Connections',
    //     rows: [
    //         { id: 'connection-mode', label: 'Connection Mode', keys: ['C'] },
    //         { id: 'switch-between-items', label: 'Switch between items', keys: ['Tab'] },
    //         { id: 'switch-between-connections', label: 'Switch between connections', keys: ['Ctrl', 'arrows'] },
    //         { id: 'confirm-connection', label: 'Confirm', keys: ['Enter'] },
    //     ],
    // },
    {
        id: 'opening-editing',
        title: 'Opening/editing items',
        rows: [
            // { id: 'open-item', label: 'Open/activate item', keys: ['Enter'] },
            // { id: 'start-edit', label: 'Start editing the text', keys: ['Enter'] },
            { id: 'open-node-menu', label: 'Open node create menu', keys: ['Left click'] },
            { id: 'exit-edit', label: 'Exit edit mode', keys: ['Esc'] },
        ],
    },
    {
        id: 'zoom',
        title: 'Zoom',
        rows: [
            { id: 'zoom-in', label: 'Zoom in', keys: ['Ctrl', 'Mouse wheel up'] },
            { id: 'zoom-out', label: 'Zoom out', keys: ['Ctrl', 'Mouse wheel down'] },
            // { id: 'fit', label: 'Fit', keys: ['Ctrl', '0'] },
        ],
    },
    {
        id: 'delete',
        title: 'Delete',
        rows: [
            { id: 'delete-item', label: 'Delete', keys: ['Delete'] },
            { id: 'undo', label: 'Undo', keys: ['Ctrl', 'Z'] },
            { id: 'redo', label: 'Redo', keys: ['Ctrl', 'Shift', 'Z'] },
            { id: 'redo-alt', label: 'Redo', keys: ['Ctrl', 'Y'] },
        ],
    },
    {
        id: 'filling-data',
        title: 'Filling in data',
        rows: [
            { id: 'confirm', label: 'Confirm', keys: ['Enter'] },
            // { id: 'new-line', label: 'New line', keys: ['Shift', 'arrows'] },
        ],
    }];