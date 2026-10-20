import { DatePipe } from '@angular/common';
import { Component, computed, DestroyRef, inject, input, linkedSignal, output } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent, CheckboxComponent, ConfirmationDialogService } from '@shared/components';
import { escapeHtml, formatFileSize } from '@shared/utils';

import { PackageReview, PluginBuiltInRoleDefaults, PluginSettingDeclaration } from '../../models/plugin-admin.model';
import {
    PLUGIN_SIGNATURE_LABELS,
    PLUGIN_TRUST_LABELS,
    pluginActionLabels,
    pluginTrustTone,
} from '../../utils/plugin-display.util';
import { PluginBadgeComponent } from '../plugin-badge/plugin-badge.component';
import { PluginIconComponent } from '../plugin-icon/plugin-icon.component';

/** Shown above an untrusted package's details; the SuperAdmin must acknowledge it before approving. */
export const UNTRUSTED_PACKAGE_WARNING =
    'This package is not signed by a key this deployment trusts. Installing it runs code nobody here has verified, ' +
    'with the access listed below.';

/** The only icon sources a review may carry; anything else is not shown. */
const ICON_DATA_URL_PREFIXES = ['data:image/svg+xml;base64,', 'data:image/png;base64,'];

export interface PluginApproveRequest {
    untrustedAcknowledged: boolean;
}

/**
 * Everything in a package a SuperAdmin decides on: identity and publisher, trust and signature, review warnings, the
 * access it declares to EpicStaff, the permissions it gives people (with the built-in role defaults), public paths,
 * outbound hosts, settings, limits, hooks and the package itself.
 *
 * For a pending package it offers Approve and Reject. Approving an untrusted package needs the acknowledgement box
 * ticked; rejecting asks for confirmation. The panel only asks — its container calls the API.
 */
@Component({
    selector: 'app-plugin-review-panel',
    imports: [ButtonComponent, CheckboxComponent, DatePipe, PluginBadgeComponent, PluginIconComponent],
    templateUrl: './plugin-review-panel.component.html',
    styleUrl: './plugin-review-panel.component.scss',
})
export class PluginReviewPanelComponent {
    readonly review = input.required<PackageReview>();
    /** An approve or reject request is under way. */
    readonly busy = input(false);
    readonly approveRequested = output<PluginApproveRequest>();
    readonly rejectRequested = output<void>();

    /** Reset for every package shown. */
    protected readonly acknowledged = linkedSignal({ source: () => this.review().id, computation: () => false });
    protected readonly isUntrusted = computed(() => this.review().trust === 'untrusted');
    protected readonly isPending = computed(() => this.review().review_state === 'pending');
    protected readonly canApprove = computed(
        () => this.isPending() && !this.busy() && (!this.isUntrusted() || this.acknowledged())
    );
    protected readonly iconSource = computed(() => {
        const source = this.review().icon_data_url;
        return ICON_DATA_URL_PREFIXES.some((prefix) => source.startsWith(prefix)) ? source : null;
    });
    protected readonly trustLabel = computed(() => PLUGIN_TRUST_LABELS[this.review().trust]);
    protected readonly trustTone = computed(() => pluginTrustTone(this.review().trust));
    protected readonly signatureLabel = computed(() => PLUGIN_SIGNATURE_LABELS[this.review().signature]);
    protected readonly packageSize = computed(() => formatFileSize(this.review().size, 'auto'));
    protected readonly spaSize = computed(() => formatFileSize(this.review().contents.spa_bytes, 'auto'));
    /** The untrusted warning is the banner above; the list holds the others. */
    protected readonly otherWarnings = computed(() =>
        this.review().warnings.filter((warning) => warning.code !== 'untrusted_package')
    );
    protected readonly publicPaths = computed(() =>
        this.review().public_paths.map((publicPath) => ({
            ...publicPath,
            matchLabel: publicPath.match === 'prefix' ? 'and below' : '',
            methodsLabel: publicPath.methods.join(', '),
        }))
    );
    protected readonly declaredAccess = computed(() =>
        this.review().access.map((entry) => ({ ...entry, actionLabels: pluginActionLabels(entry.actions) }))
    );
    protected readonly hooksLabel = computed(() => {
        const hooks = this.review().hooks;
        const enabled = [
            hooks.install ? 'Install' : null,
            hooks.upgrade ? 'Upgrade' : null,
            hooks.org_removed ? 'Organization removed' : null,
        ].filter((hook): hook is string => hook !== null);
        return enabled.length > 0 ? enabled.join(', ') : 'None';
    });

    protected readonly untrustedWarning = UNTRUSTED_PACKAGE_WARNING;

    private readonly confirmation = inject(ConfirmationDialogService);
    private readonly destroyRef = inject(DestroyRef);

    protected defaultRoles(defaults: PluginBuiltInRoleDefaults): string {
        const roles = [
            defaults.org_admin ? 'Org Admin' : null,
            defaults.member ? 'Member' : null,
            defaults.viewer ? 'Viewer' : null,
        ].filter((role): role is string => role !== null);
        return roles.length > 0 ? roles.join(', ') : 'No built-in role';
    }

    protected settingRequirement(setting: PluginSettingDeclaration): string {
        if (!setting.required) return 'No';
        return setting.has_default ? 'Yes, has a default' : 'Yes';
    }

    protected approve(): void {
        if (!this.canApprove()) return;
        this.approveRequested.emit({ untrustedAcknowledged: this.isUntrusted() && this.acknowledged() });
    }

    protected reject(): void {
        if (!this.isPending() || this.busy()) return;
        const review = this.review();
        this.confirmation
            .confirm({
                title: 'Reject this package?',
                message: `${escapeHtml(review.name)} ${escapeHtml(review.version)} will be deleted from EpicStaff.`,
                type: 'danger',
                confirmText: 'Reject',
                cancelText: 'Cancel',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((confirmed) => {
                if (confirmed === true) this.rejectRequested.emit();
            });
    }
}
