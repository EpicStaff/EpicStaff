import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { of } from 'rxjs';

import { PackageReview } from '../../models/plugin-admin.model';
import { buildPackageReview } from '../../testing/plugin-fixtures';
import {
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

    it('offers no actions for a package that is no longer pending', () => {
        render(buildPackageReview({ review_state: 'approved', approved_at: '2026-10-20T11:00:00Z' }));

        expect(element.querySelector('.review__actions')).toBeNull();
    });

    it('shows no icon whose source is not an image data URL', () => {
        render(buildPackageReview({ icon_data_url: 'https://evil.example/track.svg' }));

        expect(element.querySelector('img')).toBeNull();
    });
});
