import { Component, EventEmitter, Input, Output } from '@angular/core';

import { AppIconComponent } from '../../app-icon/app-icon.component';

@Component({
    selector: 'app-icon-button',
    standalone: true,
    imports: [AppIconComponent],
    template: `
        <button
            type="button"
            class="icon-button"
            [style.width]="size"
            [style.height]="size"
            (click)="onButtonClick()"
            [disabled]="disabled"
            [attr.aria-label]="ariaLabel"
        >
            <app-icon [icon]="icon" [size]="iconSize" [ariaLabel]="ariaLabel"></app-icon>
        </button>
    `,
    styles: [
        `
            .icon-button {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border: none;
                background: transparent;
                cursor: pointer;
                border-radius: 4px;
                transition: background-color 0.2s ease;
                padding: 0;

                &:hover:not(:disabled) {
                    background-color: rgba(255, 255, 255, 0.1);
                }

                &:active:not(:disabled) {
                    background-color: rgba(255, 255, 255, 0.15);
                }

                &:disabled {
                    cursor: not-allowed;
                    opacity: 0.5;
                }

                app-icon {
                    color: white;
                }
            }
        `,
    ],
})
export class IconButtonComponent {
    @Input() icon: string = '';
    @Input() size: string = '1.5rem';
    @Input() ariaLabel: string = '';
    @Input() disabled: boolean = false;
    @Output() onClick = new EventEmitter<void>();

    get iconSize(): string {
        const sizeValue = parseFloat(this.size);
        const unit = this.size.replace(/[\d.]/g, '');
        return `${sizeValue * 0.6}${unit}`;
    }

    onButtonClick(): void {
        if (!this.disabled) {
            this.onClick.emit();
        }
    }
}
