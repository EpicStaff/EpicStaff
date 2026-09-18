import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';

import { ToastService } from '../../../services/notifications';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../buttons';
import { TooltipComponent } from '../tooltip/tooltip.component';

export type CopyFieldInfoType = 'info' | 'warning';

@Component({
    selector: 'app-copy-field',
    templateUrl: './copy-field.component.html',
    styleUrls: ['./copy-field.component.scss'],
    imports: [AppSvgIconComponent, TooltipComponent, ButtonComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CopyFieldComponent {
    private readonly toast = inject(ToastService);

    readonly value = input.required<string>();
    readonly tooltipText = input<string>('');
    readonly label = input<string>('');
    readonly info = input<string | null>(null);
    readonly infoType = input<CopyFieldInfoType>('info');
    readonly hidden = input<boolean>(false);

    readonly onCopied = output<void>();
    protected readonly isCopied = signal(false);

    protected readonly isMasked = signal(false);

    protected readonly displayValue = computed(() =>
        this.isMasked() ? '•'.repeat(Math.max(this.value().length, 12)) : this.value()
    );

    constructor() {
        // Sync initial masked state from the input. Signal inputs are populated
        // before the constructor runs, so reading it here is safe.
        this.isMasked.set(this.hidden());
    }

    protected toggleVisibility(): void {
        this.isMasked.update((v) => !v);
    }

    protected onCopy(): void {
        const value = this.value();
        if (!navigator.clipboard) {
            this.toast.error('Copy is not supported in this browser');
            return;
        }
        navigator.clipboard.writeText(value).then(
            () => {
                this.isCopied.set(true);
                this.toast.info('Copied to clipboard');
                this.onCopied.emit();
            },
            () => this.toast.error('Failed to copy to clipboard')
        );
    }
}
