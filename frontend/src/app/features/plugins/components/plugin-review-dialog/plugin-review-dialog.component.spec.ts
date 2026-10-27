import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { Observable, of, throwError } from 'rxjs';
import type { Mock } from 'vitest';

import { ToastService } from '../../../../services/notifications';
import { PackageReview, PluginApproveRequest, PluginDetail } from '../../models/plugin-admin.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildPluginDetail, buildPluginUpgrade, buildUpgradePackageReview } from '../../testing/plugin-fixtures';
import { PLUGIN_ERROR_MESSAGES } from '../../utils/plugin-error-message.util';
import { PluginReviewDialogComponent, PluginReviewDialogData } from './plugin-review-dialog.component';

describe('PluginReviewDialogComponent', () => {
    let fixture: ComponentFixture<PluginReviewDialogComponent>;
    let element: HTMLElement;
    let storage: {
        getPackageReview: Mock<(packageId: number) => Observable<PackageReview>>;
        approvePackage: Mock<(packageId: number, request: PluginApproveRequest) => Observable<PluginDetail>>;
        rejectPackage: Mock<(packageId: number) => Observable<void>>;
    };
    const dialogRef = { close: vi.fn() };
    const toast = { success: vi.fn(), error: vi.fn() };

    function open(data: PluginReviewDialogData): void {
        TestBed.configureTestingModule({
            imports: [PluginReviewDialogComponent],
            providers: [
                { provide: DIALOG_DATA, useValue: data },
                { provide: DialogRef, useValue: dialogRef },
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: ToastService, useValue: toast },
                { provide: ConfirmationDialogService, useValue: { confirm: () => of(true) } },
            ],
        });
        fixture = TestBed.createComponent(PluginReviewDialogComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    }

    function approveButton(): HTMLButtonElement {
        return element.querySelector<HTMLButtonElement>('.review__approve button')!;
    }

    function approveNewVersion(): void {
        element.querySelector<HTMLInputElement>('.upgrade__acknowledge input[type="checkbox"]')!.click();
        fixture.detectChanges();
        approveButton().click();
        fixture.detectChanges();
    }

    beforeEach(() => {
        vi.clearAllMocks();
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );
        storage = {
            getPackageReview: vi.fn(() => of(buildUpgradePackageReview())),
            approvePackage: vi.fn(() => of(buildPluginDetail({ open_upgrade: buildPluginUpgrade() }))),
            rejectPackage: vi.fn(() => of(undefined)),
        };
    });

    afterEach(() => vi.unstubAllGlobals());

    it('starts the upgrade with the body the review asks for, and says it is under way', () => {
        open({ packageId: 12 });

        approveNewVersion();

        expect(storage.approvePackage).toHaveBeenCalledWith(12, {
            access_growth_acknowledged: true,
            reviewed_against_package_id: 10,
        });
        expect(toast.success).toHaveBeenCalledWith('Upgrading Weather to 0.7.0.');
        expect(dialogRef.close).toHaveBeenCalledWith({ kind: 'approved', plugin: expect.any(Object) });
    });

    it('says the upgrade is done when it completed at once', () => {
        storage.approvePackage.mockReturnValue(of(buildPluginDetail({ current_version: '0.7.0' })));
        open({ review: buildUpgradePackageReview() });

        approveNewVersion();

        expect(toast.success).toHaveBeenCalledWith('Weather is upgraded to 0.7.0.');
    });

    it('loads the review again when it is outdated, keeps the dialog open and asks for the boxes anew', () => {
        storage.approvePackage.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 409,
                        error: { status_code: 409, code: 'review_outdated', message: 'Review outdated.' },
                    })
            )
        );
        open({ packageId: 12 });
        expect(storage.getPackageReview).toHaveBeenCalledTimes(1);

        approveNewVersion();

        expect(storage.getPackageReview).toHaveBeenCalledTimes(2);
        expect(dialogRef.close).not.toHaveBeenCalled();
        expect(element.querySelector('[role="alert"]')?.textContent).toContain(PLUGIN_ERROR_MESSAGES.review_outdated);
        expect(approveButton().disabled).toBe(true);
    });

    it('keeps the review on any other refusal, with the reasons listed', () => {
        storage.approvePackage.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 400,
                        error: {
                            status_code: 400,
                            code: 'invalid_plugin_settings',
                            message: 'Invalid settings.',
                            errors: [{ loc: 'settings.units', message: 'Choose metric or imperial.' }],
                        },
                    })
            )
        );
        open({ packageId: 12 });

        approveNewVersion();

        expect(storage.getPackageReview).toHaveBeenCalledTimes(1);
        const alert = element.querySelector('[role="alert"]')?.textContent ?? '';
        expect(alert).toContain(PLUGIN_ERROR_MESSAGES.invalid_plugin_settings);
        expect(alert).toContain('settings.units');
    });
});
