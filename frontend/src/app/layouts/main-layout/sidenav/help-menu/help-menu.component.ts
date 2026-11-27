import { Component, computed, inject, input, output } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { GuidedTourService } from '../../../../core/guided-tour';
import { AboutDialogService } from '../../../../features/about/services/about-dialog.service';
import { SystemInfoService } from '../../../../features/about/services/system-info.service';
import { shortBuildLabel } from '../../../../features/about/utils/build-info.util';

/** `popover`: a panel of its own, with a heading; `inline`: under the Help row in the sidebar drawer. */
export type HelpMenuVariant = 'popover' | 'inline';

/** The Help menu's guides: the tours the user can take now, in the order the app registers them; then About. */
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

    /** The About dialog has opened from the About row, so the owner can close what would sit under it. */
    readonly aboutOpened = output<void>();

    /** The build's short form on the About row; null while the build is not known, which hides the row. */
    protected readonly shortBuild = computed(() => {
        const info = this.systemInfoService.systemInfo();
        return info ? shortBuildLabel(info) : null;
    });

    protected readonly tours = inject(GuidedTourService).replayableTours;

    private readonly systemInfoService = inject(SystemInfoService);
    private readonly aboutDialog = inject(AboutDialogService);

    protected openAbout(): void {
        this.aboutDialog.open();
        this.aboutOpened.emit();
    }
}
