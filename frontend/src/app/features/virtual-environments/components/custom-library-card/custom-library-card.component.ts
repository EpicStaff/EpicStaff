import { Component, computed, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, formatAuthorshipTimestamp } from '@shared/components';
import { TooltipOnOverflowDirective } from '@shared/directives';

import { CustomLibrary } from '../../models/custom-library.model';
import { VenvStatusBadgeComponent } from '../venv-status-badge/venv-status-badge.component';

interface CustomLibraryCardMeta {
    lead: string;
    date: string;
    trail: string;
}

@Component({
    selector: 'app-custom-library-card',
    imports: [MatTooltipModule, AppSvgIconComponent, TooltipOnOverflowDirective, VenvStatusBadgeComponent],
    templateUrl: './custom-library-card.component.html',
    styleUrls: ['./custom-library-card.component.scss'],
})
export class CustomLibraryCardComponent {
    readonly library = input.required<CustomLibrary>();
    readonly canDelete = input<boolean>(false);

    readonly openRequested = output<void>();
    readonly deleteRequested = output<void>();

    // Null while a source archive created this library and no build has named it yet.
    protected readonly displayName = computed(() => this.library().name ?? 'Naming pending…');

    // Who uploaded the library and when, in the wording the venv card uses.
    protected readonly meta = computed<CustomLibraryCardMeta | null>(() => {
        const library = this.library();
        const owner = library.owner ? library.owner.display_name?.trim() || library.owner.email : '';
        const timestamp = formatAuthorshipTimestamp(library.created_at);
        if (!owner && !timestamp) return null;
        if (!timestamp) return { lead: owner, date: '', trail: '' };
        return {
            lead: owner ? `${owner} · ` : '',
            date: timestamp.date,
            trail: `, ${timestamp.time}`,
        };
    });

    /** The whole row opens the library, where its versions are. */
    onCardClick(): void {
        this.openRequested.emit();
    }

    onDelete(): void {
        this.deleteRequested.emit();
    }
}
