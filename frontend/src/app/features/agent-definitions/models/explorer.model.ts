import { ActionCode, ResourceCode } from '@shared/models';

export type ExplorerSectionId = 'agents' | 'storage' | 'surfaces' | 'knowledge';

/** Which agent detail sections a selection opens: both, or one with the other collapsed. */
export type AgentFocus = 'all' | 'instructions' | 'surfaces';

export type AgentSelection = { kind: 'agent'; id: number; focus: AgentFocus };

export type ExplorerSelection =
    | AgentSelection
    | { kind: 'surface'; id: number; ownerAgentId?: number }
    | { kind: 'agent-doc'; id: number; instructionIndex: number }
    | { kind: 'draft-agent'; id: null; groupId?: number | null }
    | { kind: 'draft-surface'; id: null }
    | { kind: 'storage'; path: string }
    | { kind: null; id: null };

export const NO_SELECTION: ExplorerSelection = { kind: null, id: null };

export interface ExplorerSectionDef {
    id: ExplorerSectionId;
    headerLabel: string;
    filterLabel: string;
    resourceCode: ResourceCode;
    locked?: boolean;
}

export const EXPLORER_SECTIONS: ExplorerSectionDef[] = [
    { id: 'agents', headerLabel: 'Agents', filterLabel: 'Agent', resourceCode: ResourceCode.Agents, locked: true },
    {
        id: 'surfaces',
        headerLabel: 'Shared Surfaces',
        filterLabel: 'Shared Surfaces',
        resourceCode: ResourceCode.Surfaces,
    },
    { id: 'storage', headerLabel: 'Storage', filterLabel: 'Storage', resourceCode: ResourceCode.Files },
];

/**
 * The sections the user may read, with the always-shown one locked: Agents, or Shared Surfaces for a user
 * who cannot read agents, so the explorer is never empty.
 */
export function permittedExplorerSections(
    can: (resource: ResourceCode, action: ActionCode) => boolean
): ExplorerSectionDef[] {
    const lockedId: ExplorerSectionId = can(ResourceCode.Agents, ActionCode.Read) ? 'agents' : 'surfaces';
    return EXPLORER_SECTIONS.filter((section) => can(section.resourceCode, ActionCode.Read)).map((section) => ({
        ...section,
        locked: section.id === lockedId,
    }));
}

export interface GroupAssignTarget {
    kind: 'agent' | 'surface';
    id: number;
}
