import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

@Component({
    selector: 'app-stop-session-button',
    imports: [MatTooltip],
    template: `
        <button
            type="button"
            class="stop-session-button"
            [disabled]="disabled"
            [attr.aria-label]="ariaLabel"
            [matTooltip]="tooltip"
            matTooltipPosition="above"
            (click)="onButtonClick($event)"
        >
            <span class="stop-session-button__icon"></span>
        </button>
    `,
    styleUrls: ['./stop-session-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StopSessionButtonComponent {
    @Input() disabled: boolean = false;
    @Input() ariaLabel: string = 'Stop session';
    @Input() tooltip: string = 'Stop session';
    @Output() stopClick = new EventEmitter<void>();

    onButtonClick(event: MouseEvent): void {
        event.stopPropagation();
        if (!this.disabled) {
            this.stopClick.emit();
        }
    }
}
