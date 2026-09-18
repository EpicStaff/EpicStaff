export type AgentDocType = 'boot';

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
}

export interface BranchAgentNode {
    kind: 'agent';
    agentId: number;
    label: string;
    children: BranchTreeNode[];
}

// TODO(EST-2946): backend doc storage
export interface BranchAgentDocNode {
    kind: 'agent-doc';
    agentId: number;
    docType: AgentDocType;
    label: string;
    placeholder: true;
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
            return `agent-doc:${node.agentId}:${node.docType}`;
    }
}
