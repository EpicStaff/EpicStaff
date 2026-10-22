import { ToastPosition, ToastService } from '../../services/notifications';
import { EXPORT_WARNING_DURATION_MS } from '../constants/export-warning.constants';
import { ExcludedExportEntity } from '../models/export-result.model';

const ENTITY_LABELS: Record<string, { singular: string; plural: string }> = {
    AgentDefinition: { singular: 'agent', plural: 'agents' },
    PythonCodeTool: { singular: 'Python tool', plural: 'Python tools' },
    MCPTool: { singular: 'MCP tool', plural: 'MCP tools' },
    Flow: { singular: 'subflow', plural: 'subflows' },
};

const UNKNOWN_ENTITY_LABEL = { singular: 'item', plural: 'items' };

/**
 * One sentence telling the user which child entities an export left out for lack of export permission.
 * Returns null when nothing was excluded.
 *
 *  [{ type: 'AgentDefinition', count: 3, names: ['A', 'B', 'C'] }, { type: 'PythonCodeTool', count: 2, names: [] }]
 *    → 'Exported without 3 agents (A, B, C) and 2 Python tools. You do not have permission to export these. Re-assign them after import.'
 */
export function formatExportExclusionWarning(excluded: ExcludedExportEntity[]): string | null {
    if (excluded.length === 0) {
        return null;
    }
    const parts = excluded.map(formatEntry);
    return `Exported without ${joinParts(parts)}. You do not have permission to export these. Re-assign them after import.`;
}

export function showExportExclusionWarning(
    toastService: ToastService,
    excluded: ExcludedExportEntity[],
    position?: ToastPosition
): void {
    const warning = formatExportExclusionWarning(excluded);
    if (warning) {
        toastService.warning(warning, EXPORT_WARNING_DURATION_MS, position);
    }
}

function formatEntry(entry: ExcludedExportEntity): string {
    const label = ENTITY_LABELS[entry.type] ?? UNKNOWN_ENTITY_LABEL;
    const subject = `${entry.count} ${entry.count === 1 ? label.singular : label.plural}`;
    if (entry.names.length === 0) {
        return subject;
    }
    const remaining = entry.count - entry.names.length;
    const more = remaining > 0 ? ` +${remaining} more` : '';
    return `${subject} (${entry.names.join(', ')}${more})`;
}

function joinParts(parts: string[]): string {
    if (parts.length === 1) {
        return parts[0];
    }
    return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
}
