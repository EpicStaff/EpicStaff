import { NodeListKindVisual } from '@shared/components';
import { NODE_COLORS, NodeType } from '@shared/models';

import { FLOW_NODE_TYPE_LABELS } from '../../flows/components/import-review-dialog/constants/import-review.constants';
import { RecycleBinContentKind } from '../models/recycle-bin.model';

const CONTENT_KIND_LABELS: Record<RecycleBinContentKind, string> = {
    surface: 'Surface',
    python_tool: 'Python tool',
    mcp_tool: 'MCP tool',
    knowledge_source: 'Knowledge source',
    file: 'File',
    folder: 'Folder',
    document: 'Document',
};

/** Labels of every content kind: flow node kinds as the import modal names them, plus the bin's own. */
export const RECYCLE_BIN_CONTENT_LABELS: Partial<Record<string, string>> = {
    ...FLOW_NODE_TYPE_LABELS,
    ...CONTENT_KIND_LABELS,
};

const MUTED = 'var(--text-secondary-60)';

/**
 * Icons of the non-flow kinds, from the Tabler webfont the app already ships, or the app's sprite
 * where a kind has its own icon (flow node kinds keep NODE_ICONS / NODE_COLORS). Python tools and knowledge sources reuse their flow node's colour.
 */
export const RECYCLE_BIN_CONTENT_VISUALS: Record<RecycleBinContentKind, NodeListKindVisual> = {
    // The sprite icon the agents page's explorer draws surfaces with.
    surface: { svgIcon: 'surfaces-tab', color: 'var(--color-text-primary)' },
    python_tool: { icon: 'ti ti-brand-python', color: NODE_COLORS[NodeType.PYTHON] },
    mcp_tool: { icon: 'ti ti-plug', color: MUTED },
    knowledge_source: { icon: 'ti ti-books', color: NODE_COLORS[NodeType.KNOWLEDGE_RETRIEVER] },
    file: { icon: 'ti ti-file', color: MUTED },
    folder: { icon: 'ti ti-folder', color: MUTED },
    document: { icon: 'ti ti-file-text', color: MUTED },
};
