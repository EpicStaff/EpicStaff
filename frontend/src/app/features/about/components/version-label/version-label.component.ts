import { Component, computed, inject, input, linkedSignal } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { CollapseOnOverflowDirective, TooltipWhenCollapsedDirective } from '@shared/directives';

import { AboutDialogService } from '../../services/about-dialog.service';
import { SystemInfoService } from '../../services/system-info.service';
import { buildKind, buildLabel, shortBuildLabel } from '../../utils/build-info.util';

/**
 * The running build as a quiet button that opens the About dialog. It renders nothing while the build is not known,
 * so a failed request leaves no empty button behind. The owner loads `SystemInfoService`.
 *
 * Compact (the collapsed sidebar) it shows the short form (`v1.6.0`, `3f9c2a1`, `local`); the tooltip gives the full
 * label and, under it, the kind of build. Otherwise `EpicStaff <short form>`, with a branch build's branch before the commit while it fits; when it
 * does not, the branch is dropped whole, never cut, and moves to the tooltip.
 */
@Component({
    selector: 'app-version-label',
    imports: [MatTooltip, CollapseOnOverflowDirective, TooltipWhenCollapsedDirective],
    templateUrl: './version-label.component.html',
    styleUrl: './version-label.component.scss',
    host: { '[class.version-label-host--compact]': 'compact()' },
})
export class VersionLabelComponent {
    /** The collapsed sidebar: only the short form, centred, with the full label in a tooltip on the right. */
    readonly compact = input(false);

    protected readonly shortLabel = computed(() => {
        const info = this.systemInfoService.systemInfo();
        return info ? shortBuildLabel(info) : null;
    });
    /** A branch build's branch, shown before its commit while it fits; null for a release or a local build. */
    protected readonly branch = computed(() => {
        const info = this.systemInfoService.systemInfo();
        return info && buildKind(info) === 'Developer build' ? info.git_ref : null;
    });
    /** The tooltip: the full label, then the kind of build on its own line (the About dialog's badge words). */
    protected readonly tooltip = computed(() => {
        const info = this.systemInfoService.systemInfo();
        return info ? `EpicStaff ${buildLabel(info)}\n${buildKind(info)}` : '';
    });
    /**
     * The open sidebar has dropped the branch for lack of room (`appCollapseOnOverflow`). Back to false whenever the
     * sidebar changes width class: the open button is then created anew, and its directive starts with the branch shown
     * and reports only changes.
     */
    protected readonly branchDropped = linkedSignal({ source: this.compact, computation: () => false });
    /** Starts with the text the button shows (WCAG 2.5.3), then says what it does. */
    protected readonly ariaLabel = computed(() => {
        const short = this.shortLabel();
        if (short === null) {
            return null;
        }
        if (this.compact()) {
            return `${short}, open EpicStaff build details`;
        }
        const branch = this.branchDropped() ? null : this.branch();
        const shown = branch ? `${branch} · ${short}` : short;
        return `EpicStaff ${shown}, open build details`;
    });

    private readonly systemInfoService = inject(SystemInfoService);
    private readonly aboutDialog = inject(AboutDialogService);

    protected openAbout(): void {
        this.aboutDialog.open();
    }
}
