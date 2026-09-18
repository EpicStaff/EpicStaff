import { ResourceCode } from '@shared/models';

export type ExplorerSectionId = 'agents' | 'storage' | 'surfaces' | 'knowledge';

export type ExplorerSelection =
    | { kind: 'agent'; id: number }
    | { kind: 'surface'; id: number; ownerAgentId?: number }
    | { kind: 'agent-surfaces'; id: number }
    | { kind: 'agent-doc'; id: number; docType: 'boot' }
    | { kind: 'draft-agent'; id: null }
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
