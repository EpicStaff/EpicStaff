import { Component, input } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { RouterLink, RouterLinkActive } from '@angular/router';

import { TooltipOnOverflowDirective } from '../../directives/tooltip-on-overflow.directive';
import { SideSectionNavItem } from './side-section-nav.interface';

/** A page's left menu of sections, one route each; the row of the open section is highlighted. */
@Component({
    selector: 'app-side-section-nav',
    templateUrl: './side-section-nav.component.html',
    styleUrls: ['./side-section-nav.component.scss'],
    imports: [RouterLink, RouterLinkActive, MatTooltip, TooltipOnOverflowDirective],
})
export class SideSectionNavComponent {
    readonly items = input.required<SideSectionNavItem[]>();
    /** Names the menu for screen readers, e.g. "Settings sections". */
    readonly ariaLabel = input('Sections');
}
