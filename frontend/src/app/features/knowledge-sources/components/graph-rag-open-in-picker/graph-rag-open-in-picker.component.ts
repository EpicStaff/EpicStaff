import { CdkTrapFocus } from '@angular/cdk/a11y';
import { CdkConnectedOverlay, CdkOverlayOrigin, Overlay } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import {
    LINKED_TO_LABEL_BY_TYPE,
    LINKED_TO_TARGET_TYPES,
    LinkedToTargetType,
} from '../graph-rag-linked-to-picker/linked-to-targets';

/** Overlay anchoring: start-aligned below the trigger, flipping above when there's no room. */
const OVERLAY_POSITIONS = [
    {
        originX: 'start' as const,
        originY: 'bottom' as const,
        overlayX: 'start' as const,
        overlayY: 'top' as const,
        offsetY: 4,
    },
    {
        originX: 'start' as const,
        originY: 'top' as const,
        overlayX: 'start' as const,
        overlayY: 'bottom' as const,
        offsetY: -4,
    },
];

interface OpenInRow {
    type: LinkedToTargetType;
    label: string;
}

@Component({
    selector: 'app-graph-rag-open-in-picker',
    templateUrl: './graph-rag-open-in-picker.component.html',
    styleUrls: ['./graph-rag-open-in-picker.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [AppSvgIconComponent, CdkConnectedOverlay, CdkOverlayOrigin, CdkTrapFocus],
})
export class GraphRagOpenInPickerComponent {
    // 1. Inputs / Outputs
    /**
     * Subject tables the selected node/edge can be opened in. The parent wraps the trigger in
     * `@if (allowedTargets().length)`; the defensive empty-state below only runs if the overlay
     * opens with an empty list for any reason.
     */
    readonly allowedTargets = input<readonly LinkedToTargetType[]>([]);
    readonly picked = output<LinkedToTargetType>();

    // 3. Signals & Computed
    readonly isOpen = signal(false);
    readonly rows = computed<OpenInRow[]>(() => {
        const allowed = new Set<LinkedToTargetType>(this.allowedTargets());
        // Iterate the canonical order so the list is stable across callers and renders.
        return LINKED_TO_TARGET_TYPES.filter((type) => allowed.has(type)).map((type) => ({
            type,
            label: LINKED_TO_LABEL_BY_TYPE[type],
        }));
    });

    // 5. Public template-bound
    protected readonly overlayPositions = OVERLAY_POSITIONS;

    // 6. Private fields
    private readonly overlay = inject(Overlay);
    protected readonly scrollStrategy = this.overlay.scrollStrategies.reposition();

    // 9. Public methods
    toggle(): void {
        this.isOpen.update((open) => !open);
    }

    close(): void {
        this.isOpen.set(false);
    }

    pick(type: LinkedToTargetType): void {
        this.picked.emit(type);
        this.close();
    }
}
