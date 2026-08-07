import { AgentSurfacePlace } from './agent-definition.model';

export type SurfaceCategoryId = 'every-place' | 'flow' | 'chat' | 'realtime';

export function categoryToPlace(category: SurfaceCategoryId): AgentSurfacePlace {
    return category === 'every-place' ? 'all' : category;
}

export function placeToCategory(place: AgentSurfacePlace): SurfaceCategoryId {
    return place === 'all' ? 'every-place' : place;
}

export interface SurfaceCategoryConfig {
    id: SurfaceCategoryId;
    label: string;
    moveLabel: string;
    icon: string;
    showViewSummary: boolean;
    // Optional note shown under the category header (e.g. realtime limitations).
    hint?: string;
}

export const SURFACE_CATEGORIES: readonly SurfaceCategoryConfig[] = [
    {
        id: 'every-place',
        label: 'Every-Place Surface',
        moveLabel: 'Use Everywhere',
        icon: 'surface-every-place',
        showViewSummary: false,
    },
    {
        id: 'flow',
        label: 'Flow',
        moveLabel: 'Use Only in Flow',
        icon: 'flows',
        showViewSummary: true,
    },
    {
        id: 'chat',
        label: 'Chat',
        moveLabel: 'Use Only in Chat',
        icon: 'chats',
        showViewSummary: true,
    },
    {
        id: 'realtime',
        label: 'Realtime (Voice)',
        moveLabel: 'Use Only in Realtime',
        icon: 'microphone',
        showViewSummary: true,
        hint: 'In realtime, MCP tools are ignored and only the first knowledge collection is used.',
    },
] as const;
