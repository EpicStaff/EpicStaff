import { LabelColor } from '@shared/models';

export type BranchTreeNode = BranchGroupNode | BranchSurfaceNode | BranchAgentNode | BranchAgentDocNode;

export interface BranchGroupNode {
    kind: 'group';
    id: string;
    label: string;
    icon?: string;
    children: BranchTreeNode[];
    defaultExpanded?: boolean;
}

export interface BranchSurfaceNode {
    kind: 'surface';
    surfaceId: number;
    label: string;
    locked?: boolean;
    shared?: boolean;
    ownerAgentId?: number;
    /** The shared surface's group; unset on owned surfaces, which are never grouped. */
    groupId?: number | null;
}

export interface BranchAgentNode {
    kind: 'agent';
    agentId: number;
    label: string;
    children: BranchTreeNode[];
    groupId?: number | null;
}

/** One entry of an agent's `instruction_list`, identified by its position (names change on rename). */
export interface BranchAgentDocNode {
    kind: 'agent-doc';
    agentId: number;
    instructionIndex: number;
    label: string;
}

export function nodeKey(node: BranchTreeNode): string {
    switch (node.kind) {
        case 'group':
            return `group:${node.id}`;
        case 'surface':
            return `surface:${node.ownerAgentId ?? 'shared'}:${node.surfaceId}`;
        case 'agent':
            return `agent:${node.agentId}`;
        case 'agent-doc':
            return `agent-doc:${node.agentId}:${node.instructionIndex}`;
    }
}

/** The explorer sections whose items can be put into groups. */
export type GroupedSectionId = 'agents' | 'surfaces';

/** One collapsible block of a grouped section: a group, or Ungrouped when `groupId` is null. */
export interface ExplorerGroupBlock {
    groupId: number | null;
    label: string;
    /** Null for Ungrouped, which has no color. */
    color: LabelColor | null;
    /** Items in the block regardless of the search, for the header count. */
    memberCount: number;
    /** The rows to show: every member, or only the ones matching the search. */
    nodes: BranchTreeNode[];
}

/** Collapse-state key of a group block, unique across both grouped sections. */
export function groupBlockKey(section: GroupedSectionId, groupId: number | null): string {
    return `${section}:${groupId ?? 'ungrouped'}`;
}
