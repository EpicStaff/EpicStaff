import { NodeType } from '@shared/models';

export interface NodeMenuGroup {
    title: string;
    types: readonly NodeType[];
}

// Groups in product order; nodes inside each group most-used first (by how many flows use them)
export const NODE_MENU_GROUPS = [
    {
        title: 'Data & Code',
        types: [
            NodeType.PYTHON,
            NodeType.KNOWLEDGE_RETRIEVER,
            NodeType.KEY_VALUE,
            NodeType.FILE_EXTRACTOR,
            NodeType.AUDIO_TO_TEXT,
        ],
    },
    { title: 'Agents', types: [NodeType.TASK, NodeType.AGENT] },
    { title: 'Logic', types: [NodeType.CLASSIFICATION_TABLE, NodeType.TABLE] },
    { title: 'Triggers', types: [NodeType.SCHEDULE_TRIGGER, NodeType.WEBHOOK_TRIGGER, NodeType.TELEGRAM_TRIGGER] },
    { title: 'Other', types: [NodeType.NOTE, NodeType.END] },
] as const satisfies readonly NodeMenuGroup[];

export type MenuNodeType = (typeof NODE_MENU_GROUPS)[number]['types'][number];

export const NODE_MENU_LABELS: Record<MenuNodeType, string> = {
    [NodeType.WEBHOOK_TRIGGER]: 'Webhook Trigger',
    [NodeType.TELEGRAM_TRIGGER]: 'Telegram Trigger',
    [NodeType.SCHEDULE_TRIGGER]: 'Schedule Trigger',
    [NodeType.AGENT]: 'Agent Node',
    [NodeType.TASK]: 'Task Node',
    [NodeType.TABLE]: 'Decision Table',
    [NodeType.CLASSIFICATION_TABLE]: 'Classification Decision Table',
    [NodeType.PYTHON]: 'Python Code Node',
    [NodeType.KEY_VALUE]: 'Key-Value',
    [NodeType.FILE_EXTRACTOR]: 'File Extractor',
    [NodeType.AUDIO_TO_TEXT]: 'Audio to text',
    [NodeType.KNOWLEDGE_RETRIEVER]: 'Knowledge Retriever',
    [NodeType.END]: 'End',
    [NodeType.NOTE]: 'Note',
};
