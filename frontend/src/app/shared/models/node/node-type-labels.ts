import { NodeType } from './node-type';

/** How flow nodes are named outside the editor (the import review, the recycle bin's flow contents). */
export const FLOW_NODE_TYPE_LABELS: Partial<Record<NodeType, string>> = {
    [NodeType.PYTHON]: 'Python Node',
    [NodeType.CLASSIFICATION_TABLE]: 'Classification Decision Table',
    [NodeType.WEBHOOK_TRIGGER]: 'Webhook Node',
    [NodeType.TELEGRAM_TRIGGER]: 'Telegram Node',
    [NodeType.AGENT]: 'Agent Node',
    [NodeType.TASK]: 'Task Node',
    [NodeType.SUBGRAPH]: 'Subgraph Node',
    [NodeType.START]: 'Start Node',
    [NodeType.END]: 'End Node',
    [NodeType.FILE_EXTRACTOR]: 'File Extractor Node',
    [NodeType.AUDIO_TO_TEXT]: 'Audio Transcription Node',
    [NodeType.SCHEDULE_TRIGGER]: 'Schedule Trigger Node',
    [NodeType.TABLE]: 'Decision Table Node',
    [NodeType.NOTE]: 'Note',
    [NodeType.KEY_VALUE]: 'Key-Value Node',
    [NodeType.KNOWLEDGE_RETRIEVER]: 'Knowledge Retriever Node',
};
