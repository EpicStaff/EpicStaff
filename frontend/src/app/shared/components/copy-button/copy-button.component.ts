import { ChangeDetectionStrategy, Component, inject, Input } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ToastService } from '../../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-copy-button',
    standalone: true,
    imports: [AppSvgIconComponent, MatTooltipModule],
    templateUrl: './copy-button.component.html',
    styleUrls: ['./copy-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CopyButtonComponent {
    @Input() text: string = '';
    @Input() iconSize: string = '0.875rem';
    @Input() ariaLabel: string = 'Copy to clipboard';

    private readonly toastService = inject(ToastService);

    copy(event: Event): void {
        event.stopPropagation();
        navigator.clipboard
            .writeText(this.text)
            .then(() => {
                this.toastService.success('Copied to clipboard!', 3000, 'bottom-right');
            })
            .catch(() => {
                this.toastService.error('Failed to copy', 3000, 'top-right');
            });
    }
}
