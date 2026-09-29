import { ConnectedPosition } from '@angular/cdk/overlay';

export const CONTEXT_MENU_TAB = {
    FLOW_CORE: 'flow-core',
    FLOWS: 'flows',
} as const;

export type ContextMenuTab = (typeof CONTEXT_MENU_TAB)[keyof typeof CONTEXT_MENU_TAB];

export const FLOW_GRAPH_CONTEXT_MENU_POSITIONS = [
    {
        originX: 'start',
        originY: 'top',
        overlayX: 'start',
        overlayY: 'top',
        offsetX: 2,
        offsetY: 2,
    },
    {
        originX: 'end',
        originY: 'top',
        overlayX: 'end',
        overlayY: 'top',
        offsetX: -2,
        offsetY: 2,
    },
    {
        originX: 'start',
        originY: 'bottom',
        overlayX: 'start',
        overlayY: 'bottom',
        offsetX: 2,
        offsetY: -2,
    },
    {
        originX: 'end',
        originY: 'bottom',
        overlayX: 'end',
        overlayY: 'bottom',
        offsetX: -2,
        offsetY: -2,
    },
] as const satisfies readonly ConnectedPosition[];

export const FLOW_GRAPH_CONTEXT_MENU_ITEMS = [
    { label: 'Core', type: CONTEXT_MENU_TAB.FLOW_CORE },
    { label: 'Flows', type: CONTEXT_MENU_TAB.FLOWS },
] as const satisfies readonly { label: string; type: ContextMenuTab }[];
