import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogData, ConfirmationDialogService } from '@shared/components';
import { Observable, of, throwError } from 'rxjs';
import type { Mock } from 'vitest';

import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { ToastService } from '../../../../services/notifications';
import { PluginOrgRemovedJob, PluginOrgRemovedJobQuery } from '../../models/plugin-admin.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildOrgRemovedJob } from '../../testing/plugin-fixtures';
import { PLUGIN_ERROR_MESSAGES } from '../../utils/plugin-error-message.util';
import { PLUGIN_DATA_REMOVALS_POLL_MS, PluginDataRemovalsComponent } from './plugin-data-removals.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function page(jobs: PluginOrgRemovedJob[], count = jobs.length): ApiGetRequest<PluginOrgRemovedJob> {
    return { count, next: null, previous: null, results: jobs };
}

/** Cobalt was deleted while it had Weather; Weather's hook waits for its next try. */
const COBALT = buildOrgRemovedJob({
    id: 41,
    organization: { id: 7, name: 'Cobalt', exists: false },
    grant_id: null,
    error: 'Weather answered 500: database is locked',
});
const COBALT_DONE = buildOrgRemovedJob({
    ...COBALT,
    state: 'succeeded',
    next_attempt_at: null,
    finished_at: '2026-10-21T09:02:00Z',
    error: null,
    allowed_actions: [],
});
const DELTA_FAILED = buildOrgRemovedJob({
    id: 42,
    organization: { id: 8, name: 'Delta', exists: false },
    grant_id: null,
    state: 'failed',
    attempt: 9,
    next_attempt_at: null,
    finished_at: '2026-10-28T09:00:00Z',
    error: 'Weather answered 500: database is locked',
});

describe('PluginDataRemovalsComponent', () => {
    let fixture: ComponentFixture<PluginDataRemovalsComponent>;
    let element: HTMLElement;
    let storage: {
        listOrgRemovedJobs: Mock<
            (identifier: string, query: PluginOrgRemovedJobQuery) => Observable<ApiGetRequest<PluginOrgRemovedJob>>
        >;
        retryOrgRemovedJob: Mock<(identifier: string, jobId: number) => Observable<PluginOrgRemovedJob>>;
        skipOrgRemovedJob: Mock<(identifier: string, jobId: number) => Observable<PluginOrgRemovedJob>>;
    };
    let confirm: Mock<(options: ConfirmationDialogData) => Observable<boolean | 'close'>>;
    let toast: { success: Mock; warning: Mock; error: Mock };

    function render(): void {
        fixture = TestBed.createComponent(PluginDataRemovalsComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.componentRef.setInput('identifier', 'weather');
        fixture.componentRef.setInput('pluginName', 'Weather');
        refresh();
    }

    function refresh(): void {
        fixture.detectChanges();
        TestBed.tick();
        fixture.detectChanges();
    }

    function poll(): void {
        vi.advanceTimersByTime(PLUGIN_DATA_REMOVALS_POLL_MS);
        refresh();
    }

    function text(node: Element | null | undefined): string {
        return node?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    }

    function headers(): string[] {
        return Array.from(element.querySelectorAll('.table-header .table-cell')).map((cell) => text(cell));
    }

    /** The text of each cell of the row of `organization`, keyed by its column header. */
    function rowOf(organization: string): Record<string, string> {
        const row = Array.from(element.querySelectorAll('.table-body .table-row')).find((candidate) =>
            candidate.textContent?.includes(organization)
        )!;
        const labels = headers();
        return Object.fromEntries(
            Array.from(row.querySelectorAll('.table-cell')).map((cell, column) => [labels[column], text(cell)])
        );
    }

    function rowButton(organization: string, label: string): HTMLButtonElement | undefined {
        const row = Array.from(element.querySelectorAll('.table-body .table-row')).find((candidate) =>
            candidate.textContent?.includes(organization)
        )!;
        return Array.from(row.querySelectorAll<HTMLButtonElement>('button')).find((button) => text(button) === label);
    }

    function showFinished(): void {
        element.querySelector<HTMLInputElement>('.removals__toggle input[type="checkbox"]')!.click();
        refresh();
    }

    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        storage = {
            listOrgRemovedJobs: vi.fn(() => of(page([COBALT, DELTA_FAILED]))),
            retryOrgRemovedJob: vi.fn(() => of({ ...DELTA_FAILED, state: 'pending' as const, allowed_actions: [] })),
            skipOrgRemovedJob: vi.fn(() => of({ ...DELTA_FAILED, state: 'skipped' as const, allowed_actions: [] })),
        };
        confirm = vi.fn(() => of<boolean | 'close'>(true));
        toast = { success: vi.fn(), warning: vi.fn(), error: vi.fn() };
        TestBed.configureTestingModule({
            imports: [PluginDataRemovalsComponent],
            providers: [
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                { provide: ToastService, useValue: toast },
            ],
        });
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it("lists the open data removals of deleted organizations, by the organization's name as it was", () => {
        storage.listOrgRemovedJobs.mockReturnValue(of(page([DELTA_FAILED])));
        render();

        expect(storage.listOrgRemovedJobs).toHaveBeenCalledWith('weather', {
            state: 'open',
            deletedOrganizations: true,
            page: 1,
            pageSize: 20,
        });
        expect(text(element.querySelector('.removals__title'))).toBe('Deleted organizations');
        expect(headers()).toEqual(['Organization', 'State', 'Attempts', 'Next try', 'Error', 'Actions']);
        expect(rowOf('Delta')).toEqual({
            Organization: 'Delta (deleted)',
            State: 'Failed',
            Attempts: '9',
            'Next try': '—',
            Error: 'Weather answered 500: database is locked',
            Actions: 'Retry Skip',
        });
    });

    it('shows the next try of a job waiting for one', () => {
        storage.listOrgRemovedJobs.mockReturnValue(of(page([COBALT])));
        render();

        expect(rowOf('Cobalt')['State']).toBe('Waiting');
        expect(rowOf('Cobalt')['Next try']).not.toBe('—');
    });

    it('adds the finished ones on Show finished, from the first page, and says when there are none', () => {
        storage.listOrgRemovedJobs.mockReturnValue(of(page([])));
        render();
        expect(text(element.querySelector('.removals__empty'))).toBe(
            'No data removal of a deleted organization is waiting.'
        );

        storage.listOrgRemovedJobs.mockReturnValue(of(page([COBALT_DONE])));
        showFinished();

        expect(storage.listOrgRemovedJobs).toHaveBeenLastCalledWith('weather', {
            state: 'all',
            deletedOrganizations: true,
            page: 1,
            pageSize: 20,
        });
        expect(rowOf('Cobalt')['State']).toBe('Done');
        expect(rowOf('Cobalt')['Actions']).toBe('');

        storage.listOrgRemovedJobs.mockReturnValue(of(page([])));
        showFinished();
        showFinished();
        expect(text(element.querySelector('.removals__empty'))).toBe(
            'No organization was deleted while it had Weather.'
        );
    });

    it('offers pages only when there is more than one, and loads the one picked', () => {
        storage.listOrgRemovedJobs.mockReturnValue(of(page([DELTA_FAILED], 45)));
        render();

        const pageTwo = Array.from(element.querySelectorAll<HTMLButtonElement>('app-pagination-controls button')).find(
            (button) => text(button) === '2'
        );
        pageTwo!.click();
        refresh();

        expect(storage.listOrgRemovedJobs).toHaveBeenLastCalledWith('weather', expect.objectContaining({ page: 2 }));
    });

    it('polls while a job waits or runs, and stops once none does', () => {
        render();
        expect(storage.listOrgRemovedJobs).toHaveBeenCalledTimes(1);

        poll();
        expect(storage.listOrgRemovedJobs).toHaveBeenCalledTimes(2);

        storage.listOrgRemovedJobs.mockReturnValue(of(page([DELTA_FAILED])));
        poll();
        expect(storage.listOrgRemovedJobs).toHaveBeenCalledTimes(3);

        poll();
        poll();
        expect(storage.listOrgRemovedJobs).toHaveBeenCalledTimes(3);
    });

    it('never polls when nothing waits or runs, nor while the browser tab is hidden', () => {
        storage.listOrgRemovedJobs.mockReturnValue(of(page([DELTA_FAILED])));
        render();
        poll();
        expect(storage.listOrgRemovedJobs).toHaveBeenCalledTimes(1);

        let hidden = true;
        const hiddenProperty = vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
        try {
            storage.listOrgRemovedJobs.mockReturnValue(of(page([COBALT])));
            showFinished();
            expect(storage.listOrgRemovedJobs).toHaveBeenCalledTimes(2);
            poll();
            poll();
            expect(storage.listOrgRemovedJobs).toHaveBeenCalledTimes(2);

            hidden = false;
            poll();
            expect(storage.listOrgRemovedJobs).toHaveBeenCalledTimes(3);
        } finally {
            hiddenProperty.mockRestore();
        }
    });

    it('stops polling when destroyed', () => {
        render();
        fixture.destroy();
        vi.advanceTimersByTime(PLUGIN_DATA_REMOVALS_POLL_MS * 3);

        expect(storage.listOrgRemovedJobs).toHaveBeenCalledTimes(1);
    });

    it('retries at once, and reloads', () => {
        render();

        rowButton('Delta', 'Retry')!.click();
        refresh();

        expect(confirm).not.toHaveBeenCalled();
        expect(storage.retryOrgRemovedJob).toHaveBeenCalledWith('weather', DELTA_FAILED.id);
        expect(toast.success).toHaveBeenCalledWith('Weather tries again to delete its data for Delta.');
        expect(storage.listOrgRemovedJobs).toHaveBeenCalledTimes(2);
    });

    it('skips only after confirmation, and reloads', () => {
        render();

        confirm.mockReturnValueOnce(of(false));
        rowButton('Delta', 'Skip')!.click();
        refresh();
        expect(storage.skipOrgRemovedJob).not.toHaveBeenCalled();

        rowButton('Delta', 'Skip')!.click();
        refresh();

        expect(confirm).toHaveBeenLastCalledWith(
            expect.objectContaining({
                message: "Skip? Weather's data for Delta then stays where Weather keeps it until Weather is deleted.",
            })
        );
        expect(storage.skipOrgRemovedJob).toHaveBeenCalledWith('weather', DELTA_FAILED.id);
        expect(toast.success).toHaveBeenCalledWith("Skipped. Weather's data for Delta stays until Weather is deleted.");
        expect(storage.listOrgRemovedJobs).toHaveBeenCalledTimes(2);
    });

    it('says why an action was refused, and shows the list as it is now', () => {
        storage.skipOrgRemovedJob.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 409,
                        error: { status_code: 409, code: 'org_removed_hook_not_skippable', message: 'Refused.' },
                    })
            )
        );
        render();

        rowButton('Delta', 'Skip')!.click();
        refresh();

        expect(toast.error).toHaveBeenCalledWith(PLUGIN_ERROR_MESSAGES.org_removed_hook_not_skippable);
        expect(storage.listOrgRemovedJobs).toHaveBeenCalledTimes(2);
    });

    it('shows why the list did not load, and loads it again on Retry', () => {
        storage.listOrgRemovedJobs
            .mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 502, error: null })))
            .mockReturnValue(of(page([DELTA_FAILED])));
        render();

        expect(text(element.querySelector('.removals__error'))).toContain("Couldn't load the data removals.");

        Array.from(element.querySelectorAll<HTMLButtonElement>('.removals__error button'))[0].click();
        refresh();

        expect(element.querySelector('.removals__error')).toBeNull();
        expect(rowOf('Delta')['State']).toBe('Failed');
    });
});
