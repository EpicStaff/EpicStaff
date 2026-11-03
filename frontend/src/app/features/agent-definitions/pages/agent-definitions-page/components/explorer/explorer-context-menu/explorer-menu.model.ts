import { ActionCode, ResourceCode } from '@shared/models';

import { BranchTreeNode, GroupedSectionId } from '../../../../../models/tree-node.model';

export interface ExplorerMenuItem {
    id: string;
    label: string;
    resource: ResourceCode;
    action: ActionCode;
    disabled?: boolean;
    /** Draws a color dot before the label; `null` draws an empty one (Ungrouped). */
    dotColor?: string | null;
    danger?: boolean;
    /** The item only expands these; picking one of them is the action. */
    children?: ExplorerMenuItem[];
}

export interface ExplorerMenuPosition {
    x: number;
    y: number;
}

/** The header of a group block. */
export interface GroupHeaderMenuSubject {
    kind: 'group-header';
    section: GroupedSectionId;
    groupId: number;
}

/** The Agents section header's ⋮. */
export interface SectionHeaderMenuSubject {
    kind: 'section-header';
    section: 'agents';
}

/** What an explorer menu was opened on. */
export type ExplorerMenuSubject = BranchTreeNode | GroupHeaderMenuSubject | SectionHeaderMenuSubject;
