import { DialogRef } from '@angular/cdk/dialog';
import { DOCUMENT, NgTemplateOutlet } from '@angular/common';
import { Component, computed, inject } from '@angular/core';
import {
    ButtonComponent,
    formatAuthorshipTimestamp,
    HintMessageComponent,
    IconButtonComponent,
} from '@shared/components';
import { EnterSubmitDirective } from '@shared/directives';

import { UserPreferencesService } from '../../../../services/auth/user-preferences.service';
import { ToastService } from '../../../../services/notifications';
import { SystemInfoFeatures } from '../../models/system-info.model';
import { SystemInfoService } from '../../services/system-info.service';
import {
    BuildKind,
    buildKind,
    diagnosticsText,
    isBuildMismatch,
    shortBuildLabel,
    shortSha,
    UNKNOWN,
} from '../../utils/build-info.util';

interface FeatureRow {
    label: string;
    enabled: boolean;
}

/** The id of the dialog's heading, which names the dialog (`ariaLabelledBy`). Only one About dialog is open at a time. */
export const ABOUT_DIALOG_TITLE_ID = 'about-dialog-title';

/** The badge colour of each kind of build: a release green, a branch build purple, a local build grey. */
const KIND_BADGE_MODIFIER: Record<BuildKind, string> = {
    Release: 'badge--release',
    'Developer build': 'badge--developer',
    'Local build': 'badge--local',
};

function featureRows(features: SystemInfoFeatures): FeatureRow[] {
    return [
        { label: 'Chats', enabled: features.chats },
        { label: 'Plugins', enabled: features.plugins },
        { label: 'Session audit', enabled: features.session_audit },
        { label: 'User audit', enabled: features.user_audit },
    ];
}

/** A commit as a row shows it: the short sha, and its day when known. */
interface CommitView {
    sha: string;
    day: string | null;
}

/**
 * The short sha and the commit's day, or null for a commit that is not known. The day is shown as the app's other
 * read-only dates (owner / last editor, venv cards): `MMM d, y` in the user's display time zone.
 */
function commitView(sha: string | null, date: string | null, zone: string): CommitView | null {
    if (!sha) {
        return null;
    }
    return { sha: shortSha(sha), day: formatAuthorshipTimestamp(date, zone)?.date ?? null };
}

/** The running build: version, commits of both halves, the import/export format and the feature switches. */
@Component({
    selector: 'app-about-dialog',
    imports: [ButtonComponent, IconButtonComponent, HintMessageComponent, NgTemplateOutlet, EnterSubmitDirective],
    templateUrl: './about-dialog.component.html',
    styleUrl: './about-dialog.component.scss',
})
export class AboutDialogComponent {
    protected readonly shortLabel = computed(() => {
        const info = this.systemInfoService.systemInfo();
        return info ? shortBuildLabel(info) : '';
    });
    protected readonly kind = computed(() => {
        const info = this.systemInfoService.systemInfo();
        return info ? buildKind(info) : null;
    });
    protected readonly kindModifier = computed(() => {
        const kind = this.kind();
        return kind ? KIND_BADGE_MODIFIER[kind] : '';
    });
    protected readonly branch = computed(() => this.systemInfoService.systemInfo()?.git_ref ?? UNKNOWN);
    protected readonly frontendCommit = computed(() => {
        const frontend = this.systemInfoService.frontendBuild();
        return commitView(frontend.gitSha, frontend.commitDate, this.displayZone());
    });
    protected readonly backendCommit = computed(() => {
        const info = this.systemInfoService.systemInfo();
        return commitView(info?.git_sha ?? null, info?.commit_date ?? null, this.displayZone());
    });
    protected readonly importVersion = computed(() => this.systemInfoService.systemInfo()?.import_version ?? UNKNOWN);
    protected readonly isMismatch = computed(() => {
        const info = this.systemInfoService.systemInfo();
        return info ? isBuildMismatch(info, this.systemInfoService.frontendBuild()) : false;
    });
    protected readonly features = computed(() => {
        const info = this.systemInfoService.systemInfo();
        return info ? featureRows(info.features) : [];
    });

    protected readonly titleId = ABOUT_DIALOG_TITLE_ID;
    protected readonly unknown = UNKNOWN;

    private readonly systemInfoService = inject(SystemInfoService);
    private readonly displayZone = inject(UserPreferencesService).displayZone;
    private readonly dialogRef = inject<DialogRef<void>>(DialogRef);
    private readonly toast = inject(ToastService);
    private readonly document = inject(DOCUMENT);

    protected close(): void {
        this.dialogRef.close();
    }

    protected async copy(): Promise<void> {
        const info = this.systemInfoService.systemInfo();
        const view = this.document.defaultView;
        if (!info || !view) {
            return;
        }
        const text = diagnosticsText(
            info,
            this.systemInfoService.frontendBuild(),
            { origin: this.document.location.origin, pathname: this.document.location.pathname },
            view.navigator.userAgent,
            new Date()
        );
        try {
            await view.navigator.clipboard.writeText(text);
            this.toast.success('Copied');
        } catch {
            this.toast.error("Couldn't copy");
        }
    }
}
