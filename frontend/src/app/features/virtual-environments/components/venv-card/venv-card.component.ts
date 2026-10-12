import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { DatePipe } from '@angular/common';
import { Component, computed, input, output, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

import { Venv, VenvLib } from '../../models/venv.model';
import { VenvStatusBadgeComponent } from '../venv-status-badge/venv-status-badge.component';

// Chips beyond this count collapse into a single "+N" overflow chip.
const MAX_VISIBLE_LIBS = 4;

@Component({
    selector: 'app-venv-card',
    imports: [DatePipe, OverlayModule, MatTooltipModule, AppSvgIconComponent, VenvStatusBadgeComponent],
    templateUrl: './venv-card.component.html',
    styleUrls: ['./venv-card.component.scss'],
})
export class VenvCardComponent {
    readonly venv = input.required<Venv>();
    readonly canEdit = input<boolean>(false);
    readonly canDelete = input<boolean>(false);

    readonly editRequested = output<void>();
    readonly deleteRequested = output<void>();

    readonly menuOpen = signal(false);

    readonly visibleLibs = computed<VenvLib[]>(() => this.venv().libs.slice(0, MAX_VISIBLE_LIBS));
    readonly overflowCount = computed<number>(() => Math.max(0, this.venv().libs.length - MAX_VISIBLE_LIBS));
    readonly overflowTooltip = computed<string>(() =>
        this.venv()
            .libs.slice(MAX_VISIBLE_LIBS)
            .map((lib) => this.libLabel(lib))
            .join(', ')
    );
    readonly ownerName = computed<string | null>(() => {
        const owner = this.venv().owner;
        if (!owner) return null;
        return owner.display_name?.trim() || owner.email;
    });

    protected readonly menuPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 6 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -6 },
    ];

    libLabel(lib: VenvLib): string {
        return lib.specification ? `${lib.name} ${lib.specification}` : lib.name;
    }

    toggleMenu(): void {
        this.menuOpen.update((open) => !open);
    }

    closeMenu(): void {
        this.menuOpen.set(false);
    }

    onEdit(): void {
        this.closeMenu();
        this.editRequested.emit();
    }

    onDelete(): void {
        this.deleteRequested.emit();
    }
}
