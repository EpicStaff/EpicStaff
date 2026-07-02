import { AgentSurfacePlace } from './agent-definition.model';

export type SurfaceCategoryId = 'every-place' | 'flow' | 'chat';

export function categoryToPlace(category: SurfaceCategoryId): AgentSurfacePlace {
    return category === 'every-place' ? 'all' : category;
}

export function placeToCategory(place: AgentSurfacePlace): SurfaceCategoryId {
    return place === 'all' ? 'every-place' : place;
}

export interface SurfaceCategoryConfig {
    id: SurfaceCategoryId;
    label: string;
    icon: string;
    showViewSummary: boolean;
}

export const SURFACE_CATEGORIES: readonly SurfaceCategoryConfig[] = [
    {
        id: 'every-place',
        label: 'Every-Place Surface',
        icon: 'surface-every-place',
        showViewSummary: false,
    },
    {
        id: 'flow',
        label: 'Flow',
        icon: 'flows',
        showViewSummary: true,
    },
    {
        id: 'chat',
        label: 'Chat',
        icon: 'chats',
        showViewSummary: true,
    },
] as const;
