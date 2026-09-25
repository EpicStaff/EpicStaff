import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { UserDeleteReport } from '@shared/models';
import { firstValueFrom, Observable, of, throwError } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { HardDeleteContent } from '../models/hard-delete-content.model';
import { HardDeleteFlowService, HardDeleteOptions } from './hard-delete-flow.service';

const OPTIONS: HardDeleteOptions = {
    title: 'Delete user permanently',
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
    let buildContent: ReturnType<typeof vi.fn<(report: UserDeleteReport) => HardDeleteContent>>;

    beforeEach(() => {
        confirmationService = { confirm: vi.fn() };
        toastService = { success: vi.fn(), error: vi.fn() };
        deleteFunction = vi.fn<(dryRun: boolean) => Observable<UserDeleteReport>>(() => of(PREVIEW_REPORT));
        buildContent = vi.fn<(report: UserDeleteReport) => HardDeleteContent>((report) => ({
            message: `memberships=${report.affected_resources['memberships']}`,
        }));

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

    it('opens the confirmation dialog with the content built from the preview report', async () => {
        confirmationService.confirm.mockReturnValue(of(false));

        await firstValueFrom(service.run(deleteFunction, buildContent, OPTIONS), { defaultValue: undefined });

        expect(deleteFunction).toHaveBeenCalledWith(true);
        expect(buildContent).toHaveBeenCalledWith(PREVIEW_REPORT);
        expect(confirmationService.confirm).toHaveBeenCalledWith({
            title: OPTIONS.title,
            message: 'memberships=2',
            type: 'danger',
            confirmText: 'Delete permanently',
            cancelText: 'Cancel',
        });
        expect(toastService.error).not.toHaveBeenCalled();
    });

    it('forwards caution and breakdown from the content', async () => {
        confirmationService.confirm.mockReturnValue(of(false));
        const content: HardDeleteContent = {
            message: 'Delete?',
            caution: 'Keys will stop working.',
            cautionTitle: 'Caution',
            breakdown: { title: 'Resources to delete', items: [{ label: 'Agents', count: 3 }] },
        };
        buildContent.mockReturnValue(content);

        await firstValueFrom(service.run(deleteFunction, buildContent, OPTIONS), { defaultValue: undefined });

        expect(confirmationService.confirm).toHaveBeenCalledWith(expect.objectContaining(content));
    });

    it('performs the real deletion and reports success when confirmed', async () => {
        confirmationService.confirm.mockReturnValue(of(true));

        const result = await firstValueFrom(service.run(deleteFunction, buildContent, OPTIONS));

        expect(result).toBe(true);
        expect(deleteFunction).toHaveBeenNthCalledWith(1, true);
        expect(deleteFunction).toHaveBeenNthCalledWith(2, false);
        expect(toastService.success).toHaveBeenCalledWith(OPTIONS.successMessage);
    });

    it('does not perform the real deletion when the dialog is cancelled', async () => {
        confirmationService.confirm.mockReturnValue(of(false));

        const result = await firstValueFrom(service.run(deleteFunction, buildContent, OPTIONS), {
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

        const result = await firstValueFrom(service.run(deleteFunction, buildContent, OPTIONS));

        expect(result).toBe(false);
        expect(deleteFunction).toHaveBeenNthCalledWith(2, false);
        expect(toastService.error).toHaveBeenCalledWith(OPTIONS.deleteErrorFallback);
        expect(toastService.success).not.toHaveBeenCalled();
    });

    it('shows the preview error fallback when the preview request fails', async () => {
        deleteFunction.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 500 })));

        const result = await firstValueFrom(service.run(deleteFunction, buildContent, OPTIONS));

        expect(result).toBe(false);
        expect(confirmationService.confirm).not.toHaveBeenCalled();
        expect(toastService.error).toHaveBeenCalledWith(OPTIONS.previewErrorFallback);
    });
});
