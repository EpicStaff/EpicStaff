import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, CheckboxComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, LlmLibraryModel, ResourceCode } from '@shared/models';

@Component({
    selector: 'app-llm-library-card',
    imports: [MatTooltipModule, HasPermissionDirective, AppSvgIconComponent, CheckboxComponent],
    templateUrl: './llm-library-card.component.html',
    styleUrls: ['./llm-library-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmLibraryCardComponent {
    public readonly model = input.required<LlmLibraryModel>();
    public readonly selectMode = input(false);
    public readonly selected = input(false);
    /** True while a bulk delete is in flight; disables the selection checkbox and stops
     *  selection from being toggled by a card click. */
    public readonly isDeleting = input(false);

    public readonly editClick = output<LlmLibraryModel>();
    public readonly deleteClick = output<LlmLibraryModel>();
    public readonly selectedChange = output<boolean>();

    public onCardClick(): void {
        if (!this.selectMode() || this.isDeleting()) return;
        this.selectedChange.emit(!this.selected());
    }

    public onEdit(): void {
        this.editClick.emit(this.model());
    }

    public onDelete(): void {
        this.deleteClick.emit(this.model());
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
