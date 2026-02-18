import { NodeType } from './node-type';

export const NODE_TYPE_PREFIXES: Record<NodeType, string> = {
    [NodeType.PYTHON]: 'Python-Node',
    [NodeType.PROJECT]: 'Project-Node',
    [NodeType.TASK]: 'Task-Node',
    [NodeType.AGENT]: 'Agent-Node',
    [NodeType.TOOL]: 'Tool-Node',
    [NodeType.LLM]: 'LLM-Node',
    [NodeType.EDGE]: 'Edge-Node',
    [NodeType.START]: 'Start-Node',
    [NodeType.GROUP]: 'Group',
    [NodeType.TABLE]: 'Decision-Table',
    [NodeType.NOTE]: 'Note',
    [NodeType.FILE_EXTRACTOR]: 'File Extractor',
    [NodeType.AUDIO_TO_TEXT]: 'Audio-to-text',
    [NodeType.WEBHOOK_TRIGGER]: 'Webhook Trigger',
    [NodeType.TELEGRAM_TRIGGER]: 'Telegram Trigger',
    [NodeType.END]: 'End',
    [NodeType.SUBGRAPH]: 'Flow-Node',
};
