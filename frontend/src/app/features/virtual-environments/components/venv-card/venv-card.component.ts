import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { Component, computed, input, output, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, formatAuthorshipTimestamp } from '@shared/components';
import {
    OverflowBadgeDirective,
    OverflowItemDirective,
    OverflowItemsDirective,
    TooltipOnOverflowDirective,
} from '@shared/directives';

import { Venv, VenvLib, VenvLibUpdate } from '../../models/venv.model';
import { VenvStatusBadgeComponent } from '../venv-status-badge/venv-status-badge.component';

interface VenvCardMeta {
    lead: string;
    date: string;
    trail: string;
}

@Component({
    selector: 'app-venv-card',
    imports: [
        OverlayModule,
        MatTooltipModule,
        AppSvgIconComponent,
        OverflowItemsDirective,
        OverflowItemDirective,
        OverflowBadgeDirective,
        TooltipOnOverflowDirective,
        VenvStatusBadgeComponent,
    ],
    templateUrl: './venv-card.component.html',
    styleUrls: ['./venv-card.component.scss'],
})
export class VenvCardComponent {
    readonly venv = input.required<Venv>();
    readonly canEdit = input<boolean>(false);
    readonly canDelete = input<boolean>(false);

    readonly editRequested = output<void>();
    readonly deleteRequested = output<void>();
    /** The state the star was clicked into, not the one it had. */
    readonly favoriteChange = output<boolean>();

    protected readonly hiddenLibsOpen = signal(false);
    protected readonly updatesOpen = signal(false);

    protected readonly favoriteLabel = computed(() =>
        this.venv().is_favorite ? 'Remove from favorites' : 'Add to favorites'
    );

    protected readonly updates = computed<VenvLibUpdate[]>(() => []);
    protected readonly updatableLibNames = computed(() => new Set(this.updates().map((update) => update.name)));

    protected readonly meta = computed<VenvCardMeta | null>(() => {
        const venv = this.venv();
        const owner = venv.owner ? venv.owner.display_name?.trim() || venv.owner.email : '';
        const timestamp = formatAuthorshipTimestamp(venv.created_at);
        if (!owner && !timestamp) return null;
        if (!timestamp) return { lead: owner, date: '', trail: '' };
        return {
            lead: owner ? `${owner} · ` : '',
            date: timestamp.date,
            trail: `, ${timestamp.time}`,
        };
    });

    protected readonly updatesPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -8 },
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 8 },
    ];
    protected readonly hiddenLibsPositions: ConnectedPosition[] = [
        { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -8 },
        { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 8 },
    ];

    // appOverflowItems hides chips from the end, so the hidden ones are the last `count`.
    hiddenLibs(count: number): VenvLib[] {
        return count > 0 ? this.venv().libs.slice(-count) : [];
    }

    /** The whole card opens the venv, so the row carries the action the pencil used to. */
    onCardClick(): void {
        if (!this.canEdit()) return;
        this.editRequested.emit();
    }

    onToggleFavorite(): void {
        this.favoriteChange.emit(!this.venv().is_favorite);
    }

    onDelete(): void {
        this.deleteRequested.emit();
    }
}
