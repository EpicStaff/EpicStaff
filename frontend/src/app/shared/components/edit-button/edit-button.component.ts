import { ChangeDetectionStrategy, Component, ElementRef, input, output, viewChild } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-edit-button',
    imports: [AppSvgIconComponent, MatTooltipModule],
    templateUrl: './edit-button.component.html',
    styleUrls: ['./edit-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EditButtonComponent {
    tooltip = input('Edit');
    disabled = input(false);
    ariaLabel = input<string | null>(null);

    triggered = output<void>();

    private readonly button = viewChild.required<ElementRef<HTMLButtonElement>>('button');

    focus(): void {
        this.button().nativeElement.focus();
    }
}
