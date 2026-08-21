import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, LlmLibraryModel, ResourceCode } from '@shared/models';

@Component({
    selector: 'app-llm-library-card',
    imports: [CommonModule, MatTooltipModule, HasPermissionDirective, AppSvgIconComponent],
    templateUrl: './llm-library-card.component.html',
    styleUrls: ['./llm-library-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmLibraryCardComponent {
    public readonly model = input.required<LlmLibraryModel>();

    public readonly editClick = output<LlmLibraryModel>();
    public readonly deleteClick = output<LlmLibraryModel>();

    public onEdit(): void {
        this.editClick.emit(this.model());
    }

    public onDelete(): void {
        this.deleteClick.emit(this.model());
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
