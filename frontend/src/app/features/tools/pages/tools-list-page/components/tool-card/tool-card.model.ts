/**
 * Feature-agnostic view-model consumed by ToolCardComponent. Each list
 * (custom-tools, mcp-tools) maps its DTOs into this shape so the card stays
 * decoupled from backend types.
 */
export type ToolKind = 'custom' | 'mcp';

export const ToolCardIcon: Record<ToolKind, string> = {
    custom: 'python',
    mcp: 'hub',
};

export interface ToolCardVM {
    id: number;
    kind: ToolKind;
    name: string;
    description: string;
    labelIds: number[];
    favorite: boolean;
    builtIn: boolean;
    agentSurfaceUsage?: number;
    sharedSurfaceUsage?: number;
    inlineSurfaceUsage?: number;
    unused?: boolean;
}

export type ToolCardMenuAction = 'duplicate' | 'export' | 'show_used_places' | 'view_details' | 'delete';

export interface ToolCardMenuActionEvent {
    tool: ToolCardVM;
    action: ToolCardMenuAction;
    /**
     * The card's ⋮ button when the action was chosen from its menu — a dialog the action opens should
     * close back to it, as the focused menu item dies with the menu. Absent for the usage chip.
     */
    trigger?: HTMLElement;
}
