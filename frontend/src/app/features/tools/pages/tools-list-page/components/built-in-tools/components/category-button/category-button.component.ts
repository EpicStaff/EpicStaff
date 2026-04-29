import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-category-button',
    standalone: true,
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [AppSvgIconComponent],
    template: `
        <button
            type="button"
            class="category-btn"
            [class.selected]="selected"
            (click)="clicked.emit()"
        >
            <app-svg-icon
                [icon]="icon"
                size="1.1rem"
                class="cat-icon"
            />
            <span class="cat-label">{{ label }}</span>
        </button>
    `,
    styleUrls: ['./category-button.component.scss'],
})
export class CategoryButtonComponent {
    @Input() public label!: string;
    @Input() public selected = false;
    @Input() public icon: string = '';
    @Output() public clicked = new EventEmitter<void>();
}
