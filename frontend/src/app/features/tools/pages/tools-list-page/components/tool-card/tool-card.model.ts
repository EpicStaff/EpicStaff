/**
 * Feature-agnostic view-model consumed by ToolCardComponent. Each list
 * (custom-tools, mcp-tools) maps its DTOs into this shape so the card stays
 * decoupled from backend types.
 */
export type ToolKind = 'custom' | 'mcp';

export interface ToolCardVM {
    id: number;
    kind: ToolKind;
    name: string;
    description: string;
    labelIds: number[];
    favorite: boolean;
    builtIn: boolean;
    projectsUsage?: number;
    agentsUsage?: number;
    unused?: boolean;
}

export type ToolCardMenuAction = 'duplicate' | 'export' | 'show_used_places' | 'delete';
