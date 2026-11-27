import { inject, Injectable } from '@angular/core';

import { ProfileService } from '../../services/auth/profile.service';
import { FlowViewport } from '../core/models/flow-viewport.model';

const VIEWPORT_KEY_PREFIX = 'flow-viewport:';

/**
 * The pan and zoom each user last left each flow at, kept in this browser only: every pan and zoom is not worth a
 * request. Keyed by user, so the next person on the same browser never opens a flow where somebody else left it.
 */
@Injectable({ providedIn: 'root' })
export class FlowViewportMemoryService {
    private readonly profileService = inject(ProfileService);

    remember(graphId: number, viewport: FlowViewport): void {
        const key = this.key(graphId);
        if (key === null) return;
        try {
            localStorage.setItem(key, JSON.stringify(viewport));
        } catch {
            // Storage full or blocked: the flow then opens fitted to the screen.
        }
    }

    /** Where the signed-in user left flow `graphId`; null when they never left it in this browser. */
    recall(graphId: number): FlowViewport | null {
        const key = this.key(graphId);
        if (key === null) return null;
        try {
            return toViewport(JSON.parse(localStorage.getItem(key) ?? 'null'));
        } catch {
            return null;
        }
    }

    private key(graphId: number): string | null {
        const userId = this.profileService.currentUserSignal()?.id;
        return userId === undefined ? null : `${VIEWPORT_KEY_PREFIX}${userId}:${graphId}`;
    }
}

function toViewport(value: unknown): FlowViewport | null {
    if (typeof value !== 'object' || value === null) return null;
    const { position, scale } = value as Partial<Record<keyof FlowViewport, unknown>>;
    if (!isFiniteNumber(scale) || scale <= 0 || typeof position !== 'object' || position === null) return null;
    const { x, y } = position as Partial<Record<'x' | 'y', unknown>>;
    return isFiniteNumber(x) && isFiniteNumber(y) ? { position: { x, y }, scale } : null;
}

function isFiniteNumber(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value);
}
