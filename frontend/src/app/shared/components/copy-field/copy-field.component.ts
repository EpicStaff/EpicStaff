import { Clipboard } from '@angular/cdk/clipboard';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    inject,
    input,
    linkedSignal,
    output,
    signal,
} from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

import { ToastService } from '../../../services/notifications';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../buttons';
import { TooltipComponent } from '../tooltip/tooltip.component';

export type CopyFieldInfoType = 'info' | 'warning';

@Component({
    selector: 'app-copy-field',
    templateUrl: './copy-field.component.html',
    styleUrls: ['./copy-field.component.scss'],
    imports: [AppSvgIconComponent, TooltipComponent, ButtonComponent, MatTooltip],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CopyFieldComponent {
    private readonly toast = inject(ToastService);
    private readonly clipboard = inject(Clipboard);

    readonly value = input.required<string>();
    readonly tooltipText = input<string>('');
    readonly label = input<string>('');
    readonly info = input<string | null>(null);
    readonly infoType = input<CopyFieldInfoType>('info');
    readonly hidden = input<boolean>(false);

    readonly onCopied = output<void>();
    protected readonly isCopied = signal(false);

    // Follows `hidden` until the user toggles it; inputs are not set yet when the constructor runs.
    protected readonly isMasked = linkedSignal(() => this.hidden());

    protected readonly displayValue = computed(() =>
        this.isMasked() ? '•'.repeat(Math.max(this.value().length, 12)) : this.value()
    );

    protected toggleVisibility(): void {
        this.isMasked.update((v) => !v);
    }

    protected onCopy(): void {
        if (!this.clipboard.copy(this.value())) {
            this.toast.error('Failed to copy to clipboard');
            return;
        }
        this.isCopied.set(true);
        this.toast.info('Copied to clipboard');
        this.onCopied.emit();
    }
}
