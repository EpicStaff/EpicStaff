import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, LlmLibraryModel, ResourceCode } from '@shared/models';

import { ConfigCardMoreMenuComponent } from '../config-card-more-menu/config-card-more-menu.component';

/** "View Details" was chosen on a card; `trigger` is the ⋮ button the details dialog should close back to. */
export interface LlmLibraryCardViewDetailsEvent {
    model: LlmLibraryModel;
    trigger: HTMLElement;
}

@Component({
    selector: 'app-llm-library-card',
    imports: [MatTooltipModule, HasPermissionDirective, AppSvgIconComponent, ConfigCardMoreMenuComponent],
    templateUrl: './llm-library-card.component.html',
    styleUrls: ['./llm-library-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmLibraryCardComponent {
    public readonly model = input.required<LlmLibraryModel>();

    public readonly editClick = output<LlmLibraryModel>();
    public readonly deleteClick = output<LlmLibraryModel>();
    public readonly viewDetailsClick = output<LlmLibraryCardViewDetailsEvent>();

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;

    protected onEdit(): void {
        this.editClick.emit(this.model());
    }

    protected onDelete(): void {
        this.deleteClick.emit(this.model());
    }

    protected onViewDetails(trigger: HTMLElement): void {
        this.viewDetailsClick.emit({ model: this.model(), trigger });
    }
}
