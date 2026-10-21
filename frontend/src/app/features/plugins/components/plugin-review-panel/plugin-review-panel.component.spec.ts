import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { of } from 'rxjs';

import { PackageReview } from '../../models/plugin-admin.model';
import { buildPackageReview } from '../../testing/plugin-fixtures';
import {
    OUTBOUND_HOSTS_NOTE,
    PluginApproveRequest,
    PluginReviewPanelComponent,
    UNTRUSTED_PACKAGE_WARNING,
} from './plugin-review-panel.component';

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
                        {
                            code: 'flows_use_missing',
                            message: 'The plugin can create flows but not run them.',
                        },
                    ],
                })
            )
        );

        it('shows the Untrusted banner once, the other warnings, and marks the publisher as claimed', () => {
            expect(element.querySelector('[role="alert"]')?.textContent?.trim()).toBe(UNTRUSTED_PACKAGE_WARNING);
            expect(element.textContent?.split(UNTRUSTED_PACKAGE_WARNING)).toHaveLength(2);
            expect(element.querySelector('.review__warnings')?.textContent).toContain(
                'The plugin can create flows but not run them.'
            );
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
            expect(approvals).toEqual([{ untrustedAcknowledged: true }]);
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

        it('shows no banner and no acknowledgement, and approves without one', () => {
            expect(element.querySelector('[role="alert"]')).toBeNull();
            expect(acknowledgement()).toBeNull();

            approveButton().click();

            expect(approvals).toEqual([{ untrustedAcknowledged: false }]);
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

    it('offers no actions for a package that is no longer pending', () => {
        render(buildPackageReview({ review_state: 'approved', approved_at: '2026-10-20T11:00:00Z' }));

        expect(element.querySelector('.review__actions')).toBeNull();
    });

    it('shows no icon whose source is not an image data URL', () => {
        render(buildPackageReview({ icon_data_url: 'https://evil.example/track.svg' }));

        expect(element.querySelector('img')).toBeNull();
    });
});
