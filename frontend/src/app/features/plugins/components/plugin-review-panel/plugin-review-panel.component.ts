import { DatePipe } from '@angular/common';
import { Component, computed, DestroyRef, inject, input, linkedSignal, output, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { ButtonComponent, CheckboxComponent, ConfirmationDialogService } from '@shared/components';
import { escapeHtml, formatFileSize } from '@shared/utils';
import { switchMap } from 'rxjs';

import {
    PackageReview,
    PluginApproveRequest,
    PluginBuiltInRoleDefaults,
    PluginSettingDeclaration,
} from '../../models/plugin-admin.model';
import { PLUGIN_SIGNATURE_LABELS, PLUGIN_TRUST_LABELS, pluginTrustTone } from '../../utils/plugin-display.util';
import { createNeededSettingsForm, neededSettingValues } from '../../utils/plugin-setting-value.util';
import { PluginAccessTableComponent } from '../plugin-access-table/plugin-access-table.component';
import { PluginBadgeComponent } from '../plugin-badge/plugin-badge.component';
import { PluginIconComponent } from '../plugin-icon/plugin-icon.component';
import { PluginNeededSettingsComponent } from '../plugin-needed-settings/plugin-needed-settings.component';
import { PluginUpgradeReviewComponent } from '../plugin-upgrade-review/plugin-upgrade-review.component';

/** Shown above an untrusted package's details; the SuperAdmin must acknowledge it before approving. */
export const UNTRUSTED_PACKAGE_WARNING =
    'This package is not signed by a key this deployment trusts. Installing it runs code nobody here has verified, ' +
    'with the access listed below.';

/** Under the outbound hosts a package declares. */
export const OUTBOUND_HOSTS_NOTE =
    'Reached over HTTPS on port 443 only, through the egress proxy. Every other host is refused.';

/** The Database section of a package that brings its database. */
const DATABASE_SET_UP = "Gets its own database on this deployment's plugin database server, set up when you approve.";

/** The Database section of an upgrade that keeps the database the plugin has. */
const DATABASE_KEPT = "Keeps its database on this deployment's plugin database server.";

const DATABASE_ACCESS = "Only this plugin's backend can connect to it.";

/** The only icon sources a review may carry; anything else is not shown. */
const ICON_DATA_URL_PREFIXES = ['data:image/svg+xml;base64,', 'data:image/png;base64,'];

/**
 * Everything in a package a SuperAdmin decides on: identity and publisher, trust and signature, review warnings, the
 * access it declares to EpicStaff, the permissions it gives people (with the built-in role defaults), public paths,
 * outbound hosts, its database, settings, limits, hooks and the package itself. For a new version of an installed
 * plugin, first what upgrading to it means ({@link PluginUpgradeReviewComponent}) and the settings it needs.
 *
 * For a pending package it offers Approve ("Upgrade to <version>" for a new version) and Reject. Approving needs
 * every box the server asks for ticked (an untrusted package, new access) and every needed setting filled; the boxes
 * and values start over for every review loaded. Rejecting asks for confirmation. The panel only asks, with the body
 * the approval sends; its container calls the API.
 */
@Component({
    selector: 'app-plugin-review-panel',
    imports: [
        ButtonComponent,
        CheckboxComponent,
        DatePipe,
        PluginAccessTableComponent,
        PluginBadgeComponent,
        PluginIconComponent,
        PluginNeededSettingsComponent,
        PluginUpgradeReviewComponent,
    ],
    templateUrl: './plugin-review-panel.component.html',
    styleUrl: './plugin-review-panel.component.scss',
})
export class PluginReviewPanelComponent {
    readonly review = input.required<PackageReview>();
    /** An approve or reject request is under way. */
    readonly busy = input(false);
    /** The body the approval sends. */
    readonly approveRequested = output<PluginApproveRequest>();
    readonly rejectRequested = output<void>();

    /** Reset for every review shown, a reloaded one of the same package too. */
    protected readonly acknowledged = linkedSignal({ source: () => this.review(), computation: () => false });
    protected readonly growthAcknowledged = linkedSignal({ source: () => this.review(), computation: () => false });
    protected readonly isUntrusted = computed(() => this.review().trust === 'untrusted');
    protected readonly isPending = computed(() => this.review().review_state === 'pending');
    protected readonly upgrade = computed(() => this.review().upgrade);
    protected readonly needsGrowthAcknowledgement = computed(
        () => this.review().access_growth?.requires_acknowledgement === true
    );
    protected readonly neededSettings = computed(() => this.upgrade()?.settings.needed ?? []);
    /** A new form for every review shown. */
    protected readonly neededForm = computed(() => createNeededSettingsForm(this.neededSettings()));
    /** Bumped on every change of a needed setting, so the values below follow the form. */
    private readonly neededRevision = signal(0);
    /** What the approval sends for the needed settings; `null` while one is missing or not valid. */
    private readonly neededValues = computed(() => {
        this.neededRevision();
        return neededSettingValues(this.neededSettings(), this.neededForm());
    });
    protected readonly canApprove = computed(
        () =>
            this.isPending() &&
            !this.busy() &&
            (!this.isUntrusted() || this.acknowledged()) &&
            (!this.needsGrowthAcknowledgement() || this.growthAcknowledged()) &&
            this.neededValues() !== null
    );
    protected readonly approveLabel = computed(() =>
        this.upgrade() ? `Upgrade to ${this.review().version}` : 'Approve'
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
    /**
     * What approving sets up for a package with a database; `null` without one. An upgrade runs only the migrations its
     * database has not applied, which the server lists, so it counts those rather than every file in the package.
     */
    protected readonly databaseText = computed(() => {
        const { contents, upgrade } = this.review();
        if (!contents.has_database) return null;
        if (!upgrade) {
            const migrations = migrationsRun(contents.migration_count, null);
            return `${DATABASE_SET_UP} ${migrations} before the backend first starts. ${DATABASE_ACCESS}`;
        }
        const count = upgrade.migrations_added.length;
        if (upgrade.database === 'added') {
            return `${DATABASE_SET_UP} ${migrationsRun(count, null)} before the new version starts. ${DATABASE_ACCESS}`;
        }
        const migrations =
            count === 0 ? 'No new migrations run.' : `${migrationsRun(count, 'new')} before the new version starts.`;
        return `${DATABASE_KEPT} ${migrations} ${DATABASE_ACCESS}`;
    });
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
    protected readonly outboundHostsNote = OUTBOUND_HOSTS_NOTE;

    private readonly confirmation = inject(ConfirmationDialogService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        toObservable(this.neededForm)
            .pipe(
                switchMap((form) => form.valueChanges),
                takeUntilDestroyed()
            )
            .subscribe(() => this.neededRevision.update((revision) => revision + 1));
    }

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
        this.approveRequested.emit(this.approveRequest());
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

    /** Only what applies: each acknowledgement the review asks for, the reviewed baseline and settings of an upgrade. */
    private approveRequest(): PluginApproveRequest {
        const request: PluginApproveRequest = {};
        if (this.isUntrusted()) request.untrusted_acknowledged = this.acknowledged();
        if (this.needsGrowthAcknowledgement()) request.access_growth_acknowledged = this.growthAcknowledged();
        const upgrade = this.upgrade();
        if (upgrade) request.reviewed_against_package_id = upgrade.baseline_package_id;
        const values = this.neededValues();
        if (values && Object.keys(values).length > 0) request.settings = values;
        return request;
    }
}

/** "1 migration runs", "3 new migrations run". */
function migrationsRun(count: number, adjective: 'new' | null): string {
    const migration = adjective ? `${adjective} migration` : 'migration';
    return count === 1 ? `1 ${migration} runs` : `${count} ${migration}s run`;
}
