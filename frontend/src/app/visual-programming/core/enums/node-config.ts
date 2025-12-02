import { NodeType } from './node-type';

export const NODE_ICONS: Record<NodeType, string> = {
    [NodeType.AGENT]: 'ti ti-robot',
    [NodeType.TASK]: 'ti ti-list-check',
    [NodeType.TOOL]: 'ti ti-tools',
    [NodeType.LLM]: 'ti ti-brain',
    [NodeType.PROJECT]: 'ti ti-folder',
    [NodeType.PYTHON]: 'ti ti-brand-python',
    [NodeType.EDGE]: 'ti ti-route-alt-left',
    [NodeType.START]: 'ti ti-player-play-filled',
    [NodeType.GROUP]: 'ti ti-apps',
    [NodeType.TABLE]: 'ti ti-table',
    [NodeType.NOTE]: 'ti ti-note',
    [NodeType.FILE_EXTRACTOR]: 'ti ti-file',
    [NodeType.WEBHOOK_TRIGGER]: 'ti ti-world',
    [NodeType.END]: 'ti ti-square-rounded',
    [NodeType.SUBGRAPH]: 'ti ti-hierarchy-2',
    [NodeType.AUDIO_TO_TEXT]: 'ti ti-music',
};

export const NODE_COLORS: Record<NodeType, string> = {
    [NodeType.AGENT]: '#8e5cd9',
    [NodeType.TASK]: '#30a46c',
    [NodeType.TOOL]: '#9f6a00',
    [NodeType.LLM]: '#e0575b',
    [NodeType.PROJECT]: '#5672cd',
    [NodeType.PYTHON]: '#ffcf3f',
    [NodeType.EDGE]: '#8e5cd9',
    [NodeType.START]: '#d3d3d3',
    [NodeType.GROUP]: '#d3d3d3',
    [NodeType.TABLE]: '#00aaff',
    [NodeType.NOTE]: '#ffffd1',
    [NodeType.FILE_EXTRACTOR]: '#2196F3',
    [NodeType.WEBHOOK_TRIGGER]: '#21f367ff',
    [NodeType.END]: '#d3d3d3',
    [NodeType.SUBGRAPH]: '#00bfa5',
    [NodeType.AUDIO_TO_TEXT]: '#ff7be9ff',
};
