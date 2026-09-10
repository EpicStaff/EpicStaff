import { NgClass } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-review-status-badge',
    imports: [NgClass, AppSvgIconComponent],
    templateUrl: './review-status-badge.component.html',
    styleUrls: ['./review-status-badge.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ReviewStatusBadgeComponent {
    public readonly reviewed = input.required<boolean>();
    public readonly notReviewedLabel = input<string>('Needs review');
    public readonly clickable = input<boolean>(false);
    public readonly toggled = output<void>();

    public onToggle(event: Event): void {
        event.stopPropagation();
        this.toggled.emit();
    }
}
