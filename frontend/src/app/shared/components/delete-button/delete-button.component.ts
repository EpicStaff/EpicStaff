import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

export type DeleteButtonVariant = 'danger' | 'default';

@Component({
    selector: 'app-delete-button',
    imports: [AppSvgIconComponent, MatTooltipModule],
    templateUrl: './delete-button.component.html',
    styleUrls: ['./delete-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DeleteButtonComponent {
    tooltip = input('Delete');
    disabled = input(false);
    variant = input<DeleteButtonVariant>('danger');

    triggered = output<void>();
}
