import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { UserDeleteReport } from '@shared/models';
import { firstValueFrom, Observable, of, throwError } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { HardDeleteFlowService, HardDeleteOptions } from './hard-delete-flow.service';

const OPTIONS: HardDeleteOptions = {
    title: 'Delete user permanently',
    caution: 'This cannot be undone.',
    successMessage: 'User deleted.',
    previewErrorFallback: 'Failed to preview user deletion.',
    deleteErrorFallback: 'Failed to delete user.',
};

const PREVIEW_REPORT: UserDeleteReport = {
    user_id: 42,
    affected_resources: { memberships: 2, api_keys: 3 },
};

describe('HardDeleteFlowService', () => {
    let service: HardDeleteFlowService;
    let confirmationService: { confirm: ReturnType<typeof vi.fn> };
    let toastService: { success: ReturnType<typeof vi.fn>; error: ReturnType<typeof vi.fn> };
    let deleteFunction: ReturnType<typeof vi.fn<(dryRun: boolean) => Observable<UserDeleteReport>>>;
    let buildMessage: ReturnType<typeof vi.fn<(report: UserDeleteReport) => string>>;

    beforeEach(() => {
        confirmationService = { confirm: vi.fn() };
        toastService = { success: vi.fn(), error: vi.fn() };
        deleteFunction = vi.fn<(dryRun: boolean) => Observable<UserDeleteReport>>(() => of(PREVIEW_REPORT));
        buildMessage = vi.fn<(report: UserDeleteReport) => string>(
            (report) => `memberships=${report.affected_resources['memberships']}`
        );

        TestBed.configureTestingModule({
            providers: [
                {
                    provide: ConfirmationDialogService,
                    useValue: confirmationService as unknown as ConfirmationDialogService,
                },
                { provide: ToastService, useValue: toastService as unknown as ToastService },
            ],
        });

        service = TestBed.inject(HardDeleteFlowService);
    });

    it('opens the confirmation dialog with the impact message built from the preview report', async () => {
        confirmationService.confirm.mockReturnValue(of(false));

        await firstValueFrom(service.run(deleteFunction, buildMessage, OPTIONS), { defaultValue: undefined });

        expect(deleteFunction).toHaveBeenCalledWith(true);
        expect(buildMessage).toHaveBeenCalledWith(PREVIEW_REPORT);
        expect(confirmationService.confirm).toHaveBeenCalledWith(
            expect.objectContaining({
                title: OPTIONS.title,
                caution: OPTIONS.caution,
                message: 'memberships=2',
            })
        );
        expect(toastService.error).not.toHaveBeenCalled();
    });

    it('performs the real deletion and reports success when confirmed', async () => {
        confirmationService.confirm.mockReturnValue(of(true));

        const result = await firstValueFrom(service.run(deleteFunction, buildMessage, OPTIONS));

        expect(result).toBe(true);
        expect(deleteFunction).toHaveBeenNthCalledWith(1, true);
        expect(deleteFunction).toHaveBeenNthCalledWith(2, false);
        expect(toastService.success).toHaveBeenCalledWith(OPTIONS.successMessage);
    });

    it('does not perform the real deletion when the dialog is cancelled', async () => {
        confirmationService.confirm.mockReturnValue(of(false));

        const result = await firstValueFrom(service.run(deleteFunction, buildMessage, OPTIONS), {
            defaultValue: undefined,
        });

        expect(result).toBeUndefined();
        expect(deleteFunction).toHaveBeenCalledTimes(1);
        expect(toastService.success).not.toHaveBeenCalled();
    });

    it('shows the delete error fallback when the real deletion fails after confirmation', async () => {
        confirmationService.confirm.mockReturnValue(of(true));
        deleteFunction.mockImplementation((dryRun: boolean) =>
            dryRun ? of(PREVIEW_REPORT) : throwError(() => new HttpErrorResponse({ status: 500 }))
        );

        const result = await firstValueFrom(service.run(deleteFunction, buildMessage, OPTIONS));

        expect(result).toBe(false);
        expect(deleteFunction).toHaveBeenNthCalledWith(2, false);
        expect(toastService.error).toHaveBeenCalledWith(OPTIONS.deleteErrorFallback);
        expect(toastService.success).not.toHaveBeenCalled();
    });

    it('shows the preview error fallback when the preview request fails', async () => {
        deleteFunction.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 500 })));

        const result = await firstValueFrom(service.run(deleteFunction, buildMessage, OPTIONS));

        expect(result).toBe(false);
        expect(confirmationService.confirm).not.toHaveBeenCalled();
        expect(toastService.error).toHaveBeenCalledWith(OPTIONS.previewErrorFallback);
    });
});
