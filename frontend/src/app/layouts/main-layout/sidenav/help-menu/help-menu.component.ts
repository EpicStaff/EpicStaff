import { Component, inject, input, output } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { GuidedTourService } from '../../../../core/guided-tour';

/** `popover`: a panel of its own, with a heading; `inline`: under the Help row in the sidebar drawer. */
export type HelpMenuVariant = 'popover' | 'inline';

/** The Help menu's guides: the tours the user can take now, in the order the app registers them. */
@Component({
    selector: 'app-help-menu',
    imports: [AppSvgIconComponent],
    templateUrl: './help-menu.component.html',
    styleUrl: './help-menu.component.scss',
    host: {
        '[class.help-menu--popover]': "variant() === 'popover'",
        '[class.help-menu--inline]': "variant() === 'inline'",
    },
})
export class HelpMenuComponent {
    readonly variant = input<HelpMenuVariant>('popover');
    /** The key of the tour the user picked. The owner starts it, once it has closed what would cover the page. */
    readonly tourChosen = output<string>();

    protected readonly tours = inject(GuidedTourService).replayableTours;
}
