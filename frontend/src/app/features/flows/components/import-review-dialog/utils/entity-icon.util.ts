import { DEFAULT_ENTITY_ICON, ENTITY_ICONS } from '../../../../../shared/constants/entity-icons.constants';
import { ENTITY_TYPE_LABELS } from '../constants/import-review.constants';

const ENTITY_SPRITE_ICONS: Record<string, string> = {
    Flow: 'flow',
    Project: 'project',
    Agent: 'agent',
    PythonCodeTool: 'python',
    MCPTool: 'mcp-tool',
    WebhookTrigger: 'cloud',
    LLMModelTag: 'tags-filled',
    EmbeddingModelTag: 'tags-filled',
    EmbeddingConfig: 'settings-filled',
    RealtimeConfig: 'settings-filled',
    RealtimeTranscriptionConfig: 'settings-filled',
    EmbeddingModel: 'database',
};

export function getEntityTypeLabel(entityType: string): string {
    return ENTITY_TYPE_LABELS[entityType] || entityType;
}

export function getSpriteIcon(entityType: string): string | null {
    return ENTITY_SPRITE_ICONS[entityType] ?? null;
}

export function getIconColorForEntityType(entityType: string): string {
    const lightTypes = ['PythonCodeTool', 'MCPTool'];
    if (lightTypes.includes(entityType)) return 'var(--color-text-primary)';
    const grayTypes = ['Flow', 'Project'];

    return grayTypes.includes(entityType) ? 'var(--gray-400)' : 'var(--accent-color)';
}

export function getGroupIconColor(entityType: string): string {
    const lightTypes = ['PythonCodeTool', 'MCPTool', 'Flow'];
    return lightTypes.includes(entityType) ? 'var(--color-text-primary)' : getIconColorForEntityType(entityType);
}

export function getIconForEntityType(entityType: string): string {
    return ENTITY_ICONS[entityType] || DEFAULT_ENTITY_ICON;
}

export function isInlineSvgIcon(entityType: string): boolean {
    return getIconForEntityType(entityType).startsWith('<svg');
}
