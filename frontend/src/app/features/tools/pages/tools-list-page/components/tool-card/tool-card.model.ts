/**
 * Feature-agnostic view-model consumed by ToolCardComponent. Each list
 * (custom-tools, mcp-tools) maps its DTOs into this shape so the card stays
 * decoupled from backend types.
 */
export type ToolKind = 'custom' | 'mcp';

// TODO refactor this
export interface ToolCardVM {
    id: number;
    kind: ToolKind;
    name: string;
    description: string;
    labelIds: number[];
    favorite: boolean;
    builtIn: boolean;
    // Usage counters shown when the "Show usage & unused" toggle is on.
    // Populated from `${toolId}/usage-detail/` once wired.
    projectsUsage?: number;
    agentsUsage?: number;
    unused?: boolean;
}

export type ToolCardMenuAction = 'duplicate' | 'add_label' | 'show_used_places' | 'delete';
