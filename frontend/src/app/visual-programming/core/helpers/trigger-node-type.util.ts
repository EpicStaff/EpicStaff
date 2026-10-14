import { NodeType } from '@shared/models';

/**
 * The node types that start flow runs on their own (Webhook, Telegram, Schedule). Creating or changing
 * one needs Flows:Run besides Flows:Update; deleting one needs only Flows:Update, since it stops runs.
 */
const TRIGGER_NODE_TYPES: ReadonlySet<NodeType> = new Set([
    NodeType.WEBHOOK_TRIGGER,
    NodeType.TELEGRAM_TRIGGER,
    NodeType.SCHEDULE_TRIGGER,
]);

export function isTriggerNodeType(type: NodeType): boolean {
    return TRIGGER_NODE_TYPES.has(type);
}
