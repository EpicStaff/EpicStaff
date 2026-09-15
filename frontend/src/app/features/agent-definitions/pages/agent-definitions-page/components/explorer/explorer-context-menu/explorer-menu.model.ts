import { ActionCode, ResourceCode } from '@shared/models';

export interface ExplorerMenuItem {
    id: string;
    label: string;
    resource: ResourceCode;
    action: ActionCode;
    disabled?: boolean;
}

export interface ExplorerMenuPosition {
    x: number;
    y: number;
}
