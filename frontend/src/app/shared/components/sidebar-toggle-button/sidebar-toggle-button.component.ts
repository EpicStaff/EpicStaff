import { Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

/** Square icon button that opens or closes a sidebar. */
@Component({
    selector: 'app-sidebar-toggle-button',
    imports: [AppSvgIconComponent, MatTooltipModule],
    template: `
        <button
            type="button"
            class="sidebar-toggle-button"
            [attr.aria-label]="label()"
            [matTooltip]="label()"
            matTooltipPosition="right"
            (click)="toggled.emit()"
        >
            <app-svg-icon
                icon="expand-sidebar"
                size="1rem"
            />
        </button>
    `,
    styleUrl: './sidebar-toggle-button.component.scss',
})
export class SidebarToggleButtonComponent {
    /** Names the button for assistive technology and is shown as its tooltip; it should say what a click does
     *  ("Open sidebar" / "Close sidebar"), which also conveys the state, so no aria-expanded is added. */
    readonly label = input.required<string>();
    readonly toggled = output<void>();
}
