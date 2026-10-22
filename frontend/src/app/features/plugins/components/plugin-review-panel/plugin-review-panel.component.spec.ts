import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { of } from 'rxjs';

import { PackageReview, PluginApproveRequest, PluginReviewWarning } from '../../models/plugin-admin.model';
import {
    buildAccessGrowth,
    buildPackageReview,
    buildSettingNeeded,
    buildUpgradePackageReview,
    buildUpgradeReview,
} from '../../testing/plugin-fixtures';
import {
    OUTBOUND_HOSTS_NOTE,
    PluginReviewPanelComponent,
    UNTRUSTED_PACKAGE_WARNING,
} from './plugin-review-panel.component';

/** The review warnings as the server words them (packages/review.py). */
const RUNS_CODE_IN_SANDBOX_WARNING: PluginReviewWarning = {
    code: 'runs_code_in_sandbox',
    message:
        "Through flows, the plugin can have code of its choosing run in EpicStaff's sandbox, which has its own network " +
        "access. The plugin's outbound hosts do not apply to that code.",
};
const FLOWS_USE_MISSING_WARNING: PluginReviewWarning = {
    code: 'flows_use_missing',
    message:
        'The plugin may create or edit flows but not use them: it cannot run a flow itself or write schedule, ' +
        'webhook or Telegram trigger nodes. A flow it writes still runs, with its code, when someone in the ' +
        'organization runs it.',
};
const WILDCARD_OUTBOUND_HOST_WARNING: PluginReviewWarning = {
    code: 'wildcard_outbound_host',
    message: 'The plugin may call every subdomain of open-meteo.com.',
};

describe('PluginReviewPanelComponent', () => {
    let fixture: ComponentFixture<PluginReviewPanelComponent>;
    let element: HTMLElement;
    let approvals: PluginApproveRequest[];
    let rejections: number;
    const confirmation = { confirm: vi.fn(() => of<boolean | 'close'>(true)) };

    function render(review: PackageReview): void {
        fixture.componentRef.setInput('review', review);
        fixture.detectChanges();
    }

    function approveButton(): HTMLButtonElement {
        return element.querySelector<HTMLButtonElement>('.review__approve button')!;
    }

    function buttonByText(text: string): HTMLButtonElement | undefined {
        return Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find(
            (button) => button.textContent?.trim() === text
        );
    }

    /** The text of a section below its title, one element after another. */
    function section(title: string): string {
        const found = Array.from(element.querySelectorAll('.review__section')).find(
            (candidate) => candidate.querySelector('h4')?.textContent?.trim() === title
        );
        return Array.from(found?.children ?? [])
            .slice(1)
            .map((child) => child.textContent?.replace(/\s+/g, ' ').trim() ?? '')
            .join(' ');
    }

    function warnings(): string[] {
        return Array.from(element.querySelectorAll('.review__warnings li')).map(
            (item) => item.textContent?.replace(/\s+/g, ' ').trim() ?? ''
        );
    }

    function acknowledgement(): HTMLInputElement | null {
        return element.querySelector<HTMLInputElement>('.review__acknowledge input[type="checkbox"]');
    }

    beforeEach(() => {
        vi.clearAllMocks();
        // The buttons collapse to their icon on overflow, measured with a ResizeObserver; jsdom has none.
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );
        TestBed.configureTestingModule({
            imports: [PluginReviewPanelComponent],
            providers: [{ provide: ConfirmationDialogService, useValue: confirmation }],
        });
        fixture = TestBed.createComponent(PluginReviewPanelComponent);
        element = fixture.nativeElement as HTMLElement;
        approvals = [];
        rejections = 0;
        fixture.componentInstance.approveRequested.subscribe((request) => approvals.push(request));
        fixture.componentInstance.rejectRequested.subscribe(() => rejections++);
    });

    afterEach(() => vi.unstubAllGlobals());

    describe('an untrusted package', () => {
        beforeEach(() =>
            render(
                buildPackageReview({
                    trust: 'untrusted',
                    signature: 'absent',
                    signer: null,
                    publisher: { name: 'Someone', url: 'https://someone.example' },
                    // As the backend sends them: its untrusted warning is the banner's own sentence.
                    warnings: [
                        { code: 'untrusted_package', message: UNTRUSTED_PACKAGE_WARNING },
                        RUNS_CODE_IN_SANDBOX_WARNING,
                        FLOWS_USE_MISSING_WARNING,
                    ],
                })
            )
        );

        it('shows the Untrusted banner once, the other warnings, and marks the publisher as claimed', () => {
            expect(element.querySelector('[role="alert"]')?.textContent?.trim()).toBe(UNTRUSTED_PACKAGE_WARNING);
            expect(element.textContent?.split(UNTRUSTED_PACKAGE_WARNING)).toHaveLength(2);
            expect(warnings()).toEqual([RUNS_CODE_IN_SANDBOX_WARNING.message, FLOWS_USE_MISSING_WARNING.message]);
            expect(element.querySelector('.review__claimed')).not.toBeNull();
        });

        it('keeps Approve disabled until the acknowledgement is ticked', () => {
            expect(approveButton().disabled).toBe(true);
            approveButton().click();
            expect(approvals).toEqual([]);

            acknowledgement()!.click();
            fixture.detectChanges();

            expect(approveButton().disabled).toBe(false);
            approveButton().click();
            expect(approvals).toEqual([{ untrusted_acknowledged: true }]);
        });

        it('forgets the acknowledgement when another package is shown', () => {
            acknowledgement()!.click();
            fixture.detectChanges();

            render(buildPackageReview({ id: 12, trust: 'untrusted', signature: 'unknown_key' }));

            expect(approveButton().disabled).toBe(true);
            expect(acknowledgement()!.checked).toBe(false);
        });
    });

    describe('a trusted package', () => {
        beforeEach(() => render(buildPackageReview()));

        it('lists no warning when the server sends none', () => {
            expect(element.querySelector('.review__warnings')).toBeNull();
        });

        it("warns that flows run the plugin's code in the sandbox, which its outbound hosts do not bound", () => {
            render(buildPackageReview({ warnings: [RUNS_CODE_IN_SANDBOX_WARNING, WILDCARD_OUTBOUND_HOST_WARNING] }));

            expect(element.querySelector('[role="alert"]')).toBeNull();
            expect(warnings()).toEqual([RUNS_CODE_IN_SANDBOX_WARNING.message, WILDCARD_OUTBOUND_HOST_WARNING.message]);
        });

        it('shows no banner and no acknowledgement, and approves without one', () => {
            expect(element.querySelector('[role="alert"]')).toBeNull();
            expect(acknowledgement()).toBeNull();

            approveButton().click();

            expect(approvals).toEqual([{}]);
        });

        it('shows the signer, the default roles and that it declares no access', () => {
            expect(element.textContent).toContain('release');
            expect(element.textContent).toContain('0123456789abcdef');
            expect(element.textContent).toContain('Org Admin, Member');
            expect(element.textContent).toContain('None. The plugin cannot read or change anything in EpicStaff.');
        });

        it('asks before rejecting, and rejects only when confirmed', () => {
            confirmation.confirm.mockReturnValueOnce(of(false));
            buttonByText('Reject')!.click();
            expect(rejections).toBe(0);

            buttonByText('Reject')!.click();
            expect(confirmation.confirm).toHaveBeenCalledTimes(2);
            expect(rejections).toBe(1);
        });

        it('disables both actions while a request is under way', () => {
            fixture.componentRef.setInput('busy', true);
            fixture.detectChanges();

            expect(approveButton().disabled).toBe(true);
            expect(buttonByText('Reject')!.disabled).toBe(true);
        });
    });

    describe('the database and the outbound hosts', () => {
        const withDatabase = (migrationCount: number): PackageReview => {
            const review = buildPackageReview();
            return buildPackageReview({
                contents: {
                    ...review.contents,
                    has_backend: true,
                    has_database: true,
                    migration_count: migrationCount,
                },
            });
        };

        it('says what approving sets up for a package with a database, once', () => {
            render(withDatabase(3));

            expect(section('Package')).not.toContain('migration');
            expect(element.textContent?.match(/migrations? runs?/g)).toHaveLength(1);

            expect(section('Database')).toBe(
                "Gets its own database on this deployment's plugin database server, set up when you approve. " +
                    "3 migrations run before the backend first starts. Only this plugin's backend can connect to it."
            );
        });

        it('says "1 migration runs" for a single migration', () => {
            render(withDatabase(1));

            expect(section('Database')).toContain('1 migration runs before the backend first starts.');
        });

        it('counts only the new migrations of an upgrade, not every one in the package', () => {
            const upgrade = buildUpgradePackageReview();
            render(
                buildUpgradePackageReview({
                    contents: { ...upgrade.contents, migration_count: 4 },
                    upgrade: buildUpgradeReview({ migrations_added: ['004_notes.sql'] }),
                })
            );

            expect(section('Database')).toBe(
                "Keeps its database on this deployment's plugin database server. 1 new migration runs before the new " +
                    "version starts. Only this plugin's backend can connect to it."
            );
        });

        it('says when an upgrade runs no new migration, and how many run when it adds the database', () => {
            render(buildUpgradePackageReview({ upgrade: buildUpgradeReview({ migrations_added: [] }) }));
            expect(section('Database')).toContain('No new migrations run.');

            render(
                buildUpgradePackageReview({
                    upgrade: buildUpgradeReview({
                        database: 'added',
                        migrations_added: ['001_places.sql', '002_forecasts.sql', '003_place_conditions.sql'],
                    }),
                })
            );
            expect(section('Database')).toBe(
                "Gets its own database on this deployment's plugin database server, set up when you approve. " +
                    "3 migrations run before the new version starts. Only this plugin's backend can connect to it."
            );
        });

        it('says None for a package without a database', () => {
            render(buildPackageReview());

            expect(section('Database')).toBe('None.');
        });

        it('says the declared hosts are reached over HTTPS through the egress proxy, and every other is refused', () => {
            render(
                buildPackageReview({
                    outbound_hosts: [
                        {
                            host: 'geocoding-api.open-meteo.com',
                            reason: 'Looks up places by name when someone adds a saved place.',
                        },
                    ],
                })
            );

            expect(section('Outbound hosts')).toContain('geocoding-api.open-meteo.com');
            expect(section('Outbound hosts')).toContain(OUTBOUND_HOSTS_NOTE);
            expect(OUTBOUND_HOSTS_NOTE).toBe(
                'Reached over HTTPS on port 443 only, through the egress proxy. Every other host is refused.'
            );
        });

        it('says the backend cannot reach the internet without an outbound host, and no egress line', () => {
            render(buildPackageReview());

            expect(section('Outbound hosts')).toBe("None. The plugin's backend cannot reach the internet.");
        });
    });

    describe('a new version of an installed plugin', () => {
        function growthAcknowledgement(): HTMLInputElement | null {
            return element.querySelector<HTMLInputElement>('.upgrade__acknowledge input[type="checkbox"]');
        }

        function upgradeText(): string {
            return element.querySelector('app-plugin-upgrade-review')?.textContent?.replace(/\s+/g, ' ') ?? '';
        }

        function settingField(key: string): HTMLElement {
            return element.querySelector<HTMLElement>(`[data-setting-key="${key}"]`)!;
        }

        async function type(key: string, text: string): Promise<void> {
            const input = settingField(key).querySelector<HTMLInputElement>('input')!;
            input.value = text;
            input.dispatchEvent(new Event('input'));
            fixture.detectChanges();
            await fixture.whenStable();
        }

        it("warns on the new version's review too that flows run the plugin's code in the sandbox", () => {
            render(buildUpgradePackageReview({ warnings: [RUNS_CODE_IN_SANDBOX_WARNING] }));

            expect(warnings()).toEqual([RUNS_CODE_IN_SANDBOX_WARNING.message]);
        });

        it('says where it upgrades from, the new access, the changes, the backup and who goes offline', () => {
            render(buildUpgradePackageReview());

            const text = upgradeText();
            expect(text).toContain('Upgrade from 0.6.0');
            expect(text).toContain('New access — approve it to upgrade');
            expect(text).toContain('api.open-meteo.com');
            expect(text).toContain('Looks up the current temperature of saved places.');
            expect(text).toContain('Migrations: 003_place_conditions.sql');
            expect(text).toContain('Hooks: upgrade (new)');
            expect(text).toMatch(/plugin_weather \([^)]+\) is backed up before the migrations\./);
            expect(text).toContain('2 organizations are offline until their upgrade finishes.');
            expect(text).not.toContain('cannot be cancelled');
            expect(approveButton().textContent?.trim()).toBe('Upgrade to 0.7.0');
        });

        it('keeps "Upgrade to" disabled until the new access is approved, and sends the reviewed baseline', () => {
            render(buildUpgradePackageReview());

            expect(approveButton().disabled).toBe(true);
            growthAcknowledgement()!.click();
            fixture.detectChanges();
            approveButton().click();

            expect(approvals).toEqual([{ access_growth_acknowledged: true, reviewed_against_package_id: 10 }]);
        });

        it('asks for no acknowledgement when nothing grows, and still sends the baseline', () => {
            render(
                buildUpgradePackageReview({
                    access_growth: buildAccessGrowth({ requires_acknowledgement: false, outbound_hosts: [] }),
                })
            );

            expect(upgradeText()).not.toContain('New access');
            expect(growthAcknowledgement()).toBeNull();
            approveButton().click();

            expect(approvals).toEqual([{ reviewed_against_package_id: 10 }]);
        });

        it('needs both boxes for an untrusted version with new access', () => {
            render(buildUpgradePackageReview({ trust: 'untrusted', signature: 'absent', signer: null }));

            growthAcknowledgement()!.click();
            fixture.detectChanges();
            expect(approveButton().disabled).toBe(true);
            acknowledgement()!.click();
            fixture.detectChanges();
            approveButton().click();

            expect(approvals).toEqual([
                { untrusted_acknowledged: true, access_growth_acknowledged: true, reviewed_against_package_id: 10 },
            ]);
        });

        it('says when the upgrade cannot be cancelled, and which failed upgrade it replaces', () => {
            render(
                buildUpgradePackageReview({
                    upgrade: buildUpgradeReview({ cancellable: false, replaces_version: '0.7.1' }),
                })
            );

            expect(upgradeText()).toContain('Upgrade from 0.6.0 · replaces the failed upgrade to 0.7.1');
            expect(upgradeText()).toContain('Compared with 0.7.1, the version this one replaces.');
            expect(upgradeText()).toContain('This upgrade cannot be cancelled once it starts.');
        });

        it('enables "Upgrade to" only once every needed setting has a valid value, and sends them', async () => {
            render(
                buildUpgradePackageReview({
                    access_growth: null,
                    upgrade: buildUpgradeReview({
                        settings: {
                            added: ['api_key', 'refresh_minutes'],
                            removed: [],
                            needed: [
                                buildSettingNeeded({ key: 'api_key', type: 'secret', label: 'API key', values: null }),
                                buildSettingNeeded({
                                    key: 'refresh_minutes',
                                    type: 'integer',
                                    label: 'Refresh every',
                                    reason: 'invalid',
                                    values: null,
                                }),
                            ],
                        },
                    }),
                })
            );
            expect(section('Settings this version needs')).toContain('The stored value is not valid for this version.');
            expect(settingField('api_key').querySelector('input')!.type).toBe('password');
            expect(approveButton().disabled).toBe(true);

            await type('api_key', ' s3cret ');
            await type('refresh_minutes', '1.5');
            expect(approveButton().disabled).toBe(true);
            expect(settingField('refresh_minutes').textContent).toContain('Enter a whole number.');

            await type('refresh_minutes', '15');
            approveButton().click();

            expect(approvals).toEqual([
                { reviewed_against_package_id: 10, settings: { api_key: ' s3cret ', refresh_minutes: 15 } },
            ]);
        });

        it('starts over when the same package’s review is loaded again', () => {
            const review = buildUpgradePackageReview();
            render(review);
            growthAcknowledgement()!.click();
            fixture.detectChanges();

            render({ ...review });

            expect(growthAcknowledgement()!.checked).toBe(false);
            expect(approveButton().disabled).toBe(true);
        });

        it('shows the approved upgrade without a box to tick', () => {
            render(buildUpgradePackageReview({ review_state: 'approved' }));

            expect(growthAcknowledgement()).toBeNull();
            expect(element.querySelector('.review__actions')).toBeNull();
        });
    });

    it('offers no actions for a package that is no longer pending', () => {
        render(buildPackageReview({ review_state: 'approved', approved_at: '2026-10-20T11:00:00Z' }));

        expect(element.querySelector('.review__actions')).toBeNull();
    });

    it('shows no icon whose source is not an image data URL', () => {
        render(buildPackageReview({ icon_data_url: 'https://evil.example/track.svg' }));

        expect(element.querySelector('img')).toBeNull();
    });
});
