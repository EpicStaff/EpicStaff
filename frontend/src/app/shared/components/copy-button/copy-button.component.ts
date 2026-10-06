import { ChangeDetectionStrategy, Component, inject, Input, input } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ToastService } from '../../../services/notifications';
import { copyWithFeedback } from '../../utils/clipboard.util';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-copy-button',
    imports: [AppSvgIconComponent, MatTooltipModule],
    templateUrl: './copy-button.component.html',
    styleUrls: ['./copy-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CopyButtonComponent {
    @Input() text: string = '';
    @Input() iconSize: string = '0.875rem';
    @Input() ariaLabel: string = 'Copy to clipboard';
    // Copies text that is fetched on click (e.g. a value the list only previews) instead of `text`.
    readonly resolveText = input<(() => Promise<string>) | null>(null);

    private readonly toastService = inject(ToastService);

    copy(event: Event): void {
        event.stopPropagation();
        const resolveText = this.resolveText();
        copyWithFeedback(resolveText ? resolveText() : this.text, this.toastService);
    }
}
