import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogData, ConfirmationDialogService } from '@shared/components';
import { Observable, of, Subject, throwError } from 'rxjs';
import type { Mock } from 'vitest';

import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { ToastService } from '../../../../services/notifications';
import { PluginGrant } from '../../models/plugin-admin.model';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildPluginGrant } from '../../testing/plugin-fixtures';
import { PLUGIN_ERROR_MESSAGES } from '../../utils/plugin-error-message.util';
import { PluginSuspendDialogData } from '../plugin-suspend-dialog/plugin-suspend-dialog.component';
import { PLUGIN_GRANTS_POLL_MS, PluginGrantsTableComponent } from './plugin-grants-table.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function page(grants: PluginGrant[]): ApiGetRequest<PluginGrant> {
    return { count: grants.length, next: null, previous: null, results: grants };
}

const ACTIVE = buildPluginGrant();
const INSTALLING = buildPluginGrant({
    id: 6,
    organization: { id: 4, name: 'Bravo' },
    state: 'granting',
    allowed_actions: ['suspend'],
    owned_resource_count: 0,
    install_hook: { state: 'running', attempt: 1, started_at: '2026-10-21T08:00:05Z', finished_at: null, error: null },
});
const FAILED = buildPluginGrant({
    id: 7,
    organization: { id: 5, name: 'Charlie' },
    state: 'install_failed',
    allowed_actions: ['retry_install', 'suspend'],
    owned_resource_count: 1,
    last_hook_error: 'The plugin node reported no result in time',
    install_hook: {
        state: 'failed',
        attempt: 1,
        started_at: '2026-10-21T08:00:05Z',
        finished_at: '2026-10-21T08:00:35Z',
        error: 'EpicStaff answered 403: permission_denied',
    },
});
const FRONTEND_ONLY = buildPluginGrant({
    id: 8,
    organization: { id: 6, name: 'Delta' },
    service_account: null,
    install_hook: null,
    owned_resource_count: 0,
});
const SUSPENDED = buildPluginGrant({
    id: 9,
    organization: { id: 7, name: 'Echo' },
    state: 'suspended',
    allowed_actions: ['resume'],
    suspended_at: '2026-10-21T09:00:00Z',
    purge_after: '2026-11-20T09:00:00Z',
});

/** The grant as the server answers once its install runs again. */
function installing(grant: PluginGrant): PluginGrant {
    return {
        ...grant,
        state: 'granting',
        allowed_actions: ['suspend'],
        install_hook: grant.install_hook ? { ...grant.install_hook, state: 'pending' } : null,
    };
}

function conflict(code: string): HttpErrorResponse {
    return new HttpErrorResponse({ status: 409, error: { status_code: 409, code, message: 'Refused.' } });
}

describe('PluginGrantsTableComponent', () => {
    let fixture: ComponentFixture<PluginGrantsTableComponent>;
    let element: HTMLElement;
    let storage: {
        listGrants: Mock<
            (identifier: string, page: number, pageSize: number) => Observable<ApiGetRequest<PluginGrant>>
        >;
        retryInstallHook: Mock<(identifier: string, grantId: number) => Observable<PluginGrant>>;
        resumeGrant: Mock<(identifier: string, grantId: number) => Observable<PluginGrant>>;
    };
    let openSuspend: Mock<(data: PluginSuspendDialogData) => Observable<PluginGrant | undefined>>;
    let confirm: Mock<(options: ConfirmationDialogData) => Observable<boolean | 'close'>>;
    let toast: { success: Mock; error: Mock };
    let changes: number;

    function render(): void {
        fixture = TestBed.createComponent(PluginGrantsTableComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.componentRef.setInput('identifier', 'weather');
        fixture.componentRef.setInput('pluginName', 'Weather');
        fixture.componentRef.setInput('canGrant', true);
        fixture.componentInstance.grantsChanged.subscribe(() => changes++);
        refresh();
    }

    function refresh(): void {
        fixture.detectChanges();
        TestBed.tick();
        fixture.detectChanges();
    }

    function poll(): void {
        vi.advanceTimersByTime(PLUGIN_GRANTS_POLL_MS);
        refresh();
    }

    function rowOf(organization: string): HTMLElement {
        return Array.from(element.querySelectorAll<HTMLElement>('.table-row')).find((row) =>
            row.textContent?.includes(organization)
        )!;
    }

    function actionButton(organization: string, label: string): HTMLButtonElement | undefined {
        return Array.from(rowOf(organization).querySelectorAll<HTMLButtonElement>('button')).find(
            (button) => button.textContent?.trim() === label
        );
    }

    function retryButton(organization: string): HTMLButtonElement | undefined {
        return actionButton(organization, 'Retry install');
    }

    /** The labels of the row's buttons, in order. */
    function actionLabels(organization: string): string[] {
        return Array.from(rowOf(organization).querySelectorAll<HTMLButtonElement>('.grants__actions button')).map(
            (button) => button.textContent?.trim() ?? ''
        );
    }

    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        changes = 0;
        storage = {
            listGrants: vi.fn(() => of(page([ACTIVE]))),
            retryInstallHook: vi.fn(() => of(installing(FAILED))),
            resumeGrant: vi.fn(() => of({ ...SUSPENDED, state: 'active' as const, allowed_actions: ['suspend'] })),
        };
        openSuspend = vi.fn(() => of<PluginGrant | undefined>(undefined));
        confirm = vi.fn(() => of<boolean | 'close'>(true));
        toast = { success: vi.fn(), error: vi.fn() };
        TestBed.configureTestingModule({
            imports: [PluginGrantsTableComponent],
            providers: [
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: PluginDialogsService, useValue: { openSuspend } },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                { provide: ToastService, useValue: toast },
            ],
        });
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it('shows installing with a spinner, a failed install with its error and Retry install, and Active', () => {
        storage.listGrants.mockReturnValue(of(page([ACTIVE, INSTALLING, FAILED])));
        render();

        expect(rowOf('Bravo').querySelector('app-spinner2')).not.toBeNull();
        expect(rowOf('Bravo').textContent).toContain('Installing…');
        expect(retryButton('Bravo')).toBeUndefined();

        expect(rowOf('Charlie').textContent).toContain('Install failed');
        expect(rowOf('Charlie').querySelector('.grants__hook-error')?.textContent?.trim()).toBe(
            'EpicStaff answered 403: permission_denied'
        );
        expect(retryButton('Charlie')).toBeDefined();

        expect(rowOf('Acme').textContent).toContain('Active');
        expect(rowOf('Acme').querySelector('app-spinner2')).toBeNull();
        expect(retryButton('Acme')).toBeUndefined();
    });

    it('says a pending install waits for the plugin to start, and a running one installs', () => {
        storage.listGrants.mockReturnValue(
            of(
                page([
                    {
                        ...INSTALLING,
                        install_hook: { ...INSTALLING.install_hook!, state: 'pending', started_at: null },
                    },
                    { ...installing(FAILED), install_hook: { ...FAILED.install_hook!, state: 'running' } },
                ])
            )
        );
        render();

        expect(rowOf('Bravo').querySelector('.grants__installing')?.textContent?.trim()).toBe(
            'Waiting for the plugin to start'
        );
        expect(rowOf('Bravo').querySelector('app-spinner2')).not.toBeNull();
        expect(rowOf('Charlie').querySelector('.grants__installing')?.textContent?.trim()).toBe('Installing…');
        // Suspending is the way out of an install that waits for a plugin that never starts.
        expect(actionLabels('Bravo')).toEqual(['Suspend…']);
    });

    it("shows the grant's copy of the hook error when the job has none", () => {
        storage.listGrants.mockReturnValue(
            of(page([{ ...FAILED, install_hook: { ...FAILED.install_hook!, error: null } }]))
        );
        render();

        expect(rowOf('Charlie').querySelector('.grants__hook-error')?.textContent?.trim()).toBe(
            'The plugin node reported no result in time'
        );
    });

    it('shows the service account, when its key was last used, and the owned resources', () => {
        const usedAt = new Date(Date.now() - 5 * 60_000).toISOString();
        storage.listGrants.mockReturnValue(
            of(
                page([
                    { ...ACTIVE, service_account: { created_at: '2026-10-21T08:00:00Z', key_last_used_at: usedAt } },
                    INSTALLING,
                    FRONTEND_ONLY,
                ])
            )
        );
        render();

        const cells = (organization: string) =>
            Array.from(rowOf(organization).querySelectorAll('.table-cell')).map((cell) =>
                cell.textContent?.replace(/\s+/g, ' ').trim()
            );
        expect(cells('Acme')[2]).toBe('Created Oct 21, 2026 Key used 5m ago');
        expect(cells('Acme')[3]).toBe('2');
        expect(cells('Bravo')[2]).toBe('Created Oct 21, 2026 Key never used');
        expect(cells('Bravo')[3]).toBe('0');
        expect(cells('Delta')[2]).toBe('—');
        expect(element.querySelector('.table-header')?.textContent).toContain('Service account');
        expect(element.querySelector('.table-header')?.textContent).toContain('Owned resources');
    });

    it('retries a failed install only after confirmation, then shows it installing', () => {
        storage.listGrants.mockReturnValue(of(page([FAILED])));
        render();
        // What the server says once the retry is accepted.
        storage.listGrants.mockReturnValue(of(page([installing(FAILED)])));

        confirm.mockReturnValueOnce(of(false));
        retryButton('Charlie')!.click();
        expect(storage.retryInstallHook).not.toHaveBeenCalled();

        retryButton('Charlie')!.click();
        refresh();

        expect(confirm).toHaveBeenCalledTimes(2);
        expect(storage.retryInstallHook).toHaveBeenCalledWith('weather', FAILED.id);
        expect(toast.success).toHaveBeenCalledWith('Weather is installing in Charlie again.');
        expect(rowOf('Charlie').textContent).toContain('Waiting for the plugin to start');
        expect(retryButton('Charlie')).toBeUndefined();
    });

    it('says why a retry was refused and shows the grant as it is now', () => {
        storage.listGrants.mockReturnValue(of(page([FAILED])));
        storage.retryInstallHook.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 409,
                        error: { status_code: 409, code: 'hook_not_retryable', message: 'Not failed.' },
                    })
            )
        );
        render();
        storage.listGrants.mockReturnValue(of(page([ACTIVE])));

        retryButton('Charlie')!.click();
        refresh();

        expect(toast.error).toHaveBeenCalledWith(PLUGIN_ERROR_MESSAGES.hook_not_retryable);
        expect(storage.listGrants).toHaveBeenCalledTimes(2);
        expect(rowOf('Acme').textContent).toContain('Active');
    });

    it('polls its page while a grant installs, stops once none does, and tells the page the state moved', () => {
        storage.listGrants.mockReturnValue(of(page([INSTALLING])));
        render();
        expect(storage.listGrants).toHaveBeenCalledTimes(1);

        poll();
        poll();
        expect(storage.listGrants).toHaveBeenCalledTimes(3);
        expect(storage.listGrants).toHaveBeenLastCalledWith('weather', 1, 20);
        expect(changes).toBe(0);

        storage.listGrants.mockReturnValue(of(page([{ ...INSTALLING, state: 'active' }])));
        poll();
        expect(storage.listGrants).toHaveBeenCalledTimes(4);
        expect(rowOf('Bravo').textContent).toContain('Active');
        expect(changes).toBe(1);

        poll();
        poll();
        expect(storage.listGrants).toHaveBeenCalledTimes(4);
    });

    it('drops a poll still on its way when a retry reloads the page, so the failure never comes back', () => {
        const stalePoll = new Subject<ApiGetRequest<PluginGrant>>();
        storage.listGrants
            .mockReturnValueOnce(of(page([INSTALLING, FAILED])))
            .mockReturnValueOnce(stalePoll)
            .mockReturnValue(of(page([INSTALLING, installing(FAILED)])));
        render();
        // The poll asks and waits for its answer.
        poll();
        expect(storage.listGrants).toHaveBeenCalledTimes(2);

        retryButton('Charlie')!.click();
        refresh();
        expect(storage.listGrants).toHaveBeenCalledTimes(3);

        // The poll's answer was read before the retry: it still says the install failed.
        stalePoll.next(page([INSTALLING, FAILED]));
        stalePoll.complete();
        refresh();

        expect(rowOf('Charlie').textContent).toContain('Waiting for the plugin to start');
        expect(retryButton('Charlie')).toBeUndefined();
    });

    it('keeps polling after a failed poll, and clears the error once a poll answers', () => {
        storage.listGrants
            .mockReturnValueOnce(of(page([INSTALLING])))
            .mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 502, error: null })))
            .mockReturnValue(of(page([{ ...INSTALLING, state: 'active' }])));
        render();

        poll();
        expect(element.querySelector('.grants__error')?.textContent).toContain("Couldn't load the grants.");
        expect(rowOf('Bravo').textContent).toContain('Installing…');

        poll();
        expect(storage.listGrants).toHaveBeenCalledTimes(3);
        expect(element.querySelector('.grants__error')).toBeNull();
        expect(rowOf('Bravo').textContent).toContain('Active');
    });

    it('skips the polls while the browser tab is hidden', () => {
        let hidden = false;
        const hiddenProperty = vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
        try {
            storage.listGrants.mockReturnValue(of(page([INSTALLING])));
            render();
            hidden = true;
            poll();
            poll();
            expect(storage.listGrants).toHaveBeenCalledTimes(1);

            hidden = false;
            poll();
            expect(storage.listGrants).toHaveBeenCalledTimes(2);
        } finally {
            hiddenProperty.mockRestore();
        }
    });

    it('announces a state change in its cell', () => {
        storage.listGrants.mockReturnValue(of(page([INSTALLING])));
        render();

        expect(rowOf('Bravo').querySelector('.grants__state')?.getAttribute('aria-live')).toBe('polite');
    });

    it('never polls when no grant installs', () => {
        storage.listGrants.mockReturnValue(of(page([ACTIVE, FAILED])));
        render();

        poll();
        poll();

        expect(storage.listGrants).toHaveBeenCalledTimes(1);
    });

    it('stops polling when destroyed', () => {
        storage.listGrants.mockReturnValue(of(page([INSTALLING])));
        render();
        poll();
        expect(storage.listGrants).toHaveBeenCalledTimes(2);

        fixture.destroy();
        vi.advanceTimersByTime(PLUGIN_GRANTS_POLL_MS * 3);

        expect(storage.listGrants).toHaveBeenCalledTimes(2);
    });

    it("shows exactly the actions the grant allows, in the server's order, whatever its state", () => {
        storage.listGrants.mockReturnValue(
            of(
                page([
                    ACTIVE,
                    FAILED,
                    SUSPENDED,
                    // The buttons never come from the state: an active grant the server allows nothing on has none.
                    { ...FRONTEND_ONLY, allowed_actions: [] },
                    buildPluginGrant({ id: 10, organization: { id: 8, name: 'Foxtrot' }, allowed_actions: ['resume'] }),
                ])
            )
        );
        render();

        expect(actionLabels('Acme')).toEqual(['Suspend…']);
        expect(actionLabels('Charlie')).toEqual(['Retry install', 'Suspend…']);
        expect(actionLabels('Echo')).toEqual(['Resume']);
        expect(actionLabels('Delta')).toEqual([]);
        expect(actionLabels('Foxtrot')).toEqual(['Resume']);
        expect(element.querySelector('.table-header')?.textContent).toContain('Actions');
    });

    it('leaves out an action this page does not know', () => {
        const unknownAction = { ...ACTIVE, allowed_actions: ['purge', 'suspend'] } as unknown as PluginGrant;
        storage.listGrants.mockReturnValue(of(page([unknownAction])));
        render();

        expect(actionLabels('Acme')).toEqual(['Suspend…']);
    });

    it('shows a suspended grant with its suspension date and until when its data is kept', () => {
        storage.listGrants.mockReturnValue(of(page([SUSPENDED])));
        render();

        expect(rowOf('Echo').textContent).toContain('Suspended');
        expect(rowOf('Echo').querySelector('.grants__suspended-at')?.textContent?.trim()).toBe('Since Oct 21, 2026');
        expect(rowOf('Echo').querySelector('.grants__kept-until')?.textContent?.trim()).toBe(
            'Data kept until Nov 20, 2026'
        );
    });

    it('opens the suspend preview, and once suspended shows the grant, tells the page and reloads', () => {
        const suspended: PluginGrant = {
            ...ACTIVE,
            state: 'suspended',
            allowed_actions: ['resume'],
            suspended_at: '2026-10-21T09:00:00Z',
            purge_after: '2026-11-20T09:00:00Z',
        };
        openSuspend.mockReturnValue(of(suspended));
        storage.listGrants.mockReturnValue(of(page([ACTIVE])));
        render();
        storage.listGrants.mockReturnValue(of(page([suspended])));

        actionButton('Acme', 'Suspend…')!.click();
        refresh();

        expect(openSuspend).toHaveBeenCalledWith({ identifier: 'weather', pluginName: 'Weather', grant: ACTIVE });
        expect(confirm).not.toHaveBeenCalled();
        expect(toast.success).toHaveBeenCalledWith('Weather is suspended in Acme.');
        expect(changes).toBe(1);
        expect(storage.listGrants).toHaveBeenCalledTimes(2);
        expect(actionLabels('Acme')).toEqual(['Resume']);
        expect(rowOf('Acme').querySelector('.grants__kept-until')?.textContent?.trim()).toBe(
            'Data kept until Nov 20, 2026'
        );
    });

    it('reloads after the suspend preview is cancelled, and says nothing', () => {
        storage.listGrants.mockReturnValue(of(page([ACTIVE])));
        render();

        actionButton('Acme', 'Suspend…')!.click();
        refresh();

        expect(toast.success).not.toHaveBeenCalled();
        expect(changes).toBe(0);
        expect(storage.listGrants).toHaveBeenCalledTimes(2);
    });

    it('resumes only after confirmation, then shows the grant active, tells the page and reloads', () => {
        storage.listGrants.mockReturnValue(of(page([SUSPENDED])));
        render();
        storage.listGrants.mockReturnValue(of(page([{ ...SUSPENDED, state: 'active', allowed_actions: ['suspend'] }])));

        confirm.mockReturnValueOnce(of(false));
        actionButton('Echo', 'Resume')!.click();
        expect(storage.resumeGrant).not.toHaveBeenCalled();

        actionButton('Echo', 'Resume')!.click();
        refresh();

        expect(confirm).toHaveBeenLastCalledWith(
            expect.objectContaining({
                message: 'Resume Weather in Echo? Its runs work again and the plugin gets new keys.',
                confirmText: 'Resume',
            })
        );
        expect(storage.resumeGrant).toHaveBeenCalledWith('weather', SUSPENDED.id);
        expect(toast.success).toHaveBeenCalledWith('Weather is resumed in Echo.');
        expect(changes).toBe(1);
        expect(storage.listGrants).toHaveBeenCalledTimes(2);
        expect(rowOf('Echo').textContent).toContain('Active');
        expect(actionLabels('Echo')).toEqual(['Suspend…']);
    });

    it('escapes the names in the resume confirmation', () => {
        storage.listGrants.mockReturnValue(of(page([{ ...SUSPENDED, organization: { id: 7, name: '<b>Echo</b>' } }])));
        render();

        actionButton('Echo', 'Resume')!.click();

        expect(confirm.mock.calls[0][0].message).toContain('&lt;b&gt;Echo&lt;/b&gt;');
    });

    it('says why a resume was refused and shows the grant as it is now', () => {
        storage.listGrants.mockReturnValue(of(page([SUSPENDED])));
        storage.resumeGrant.mockReturnValue(throwError(() => conflict('grant_not_suspended')));
        render();
        storage.listGrants.mockReturnValue(of(page([{ ...SUSPENDED, state: 'active', allowed_actions: ['suspend'] }])));

        actionButton('Echo', 'Resume')!.click();
        refresh();

        expect(toast.error).toHaveBeenCalledWith(PLUGIN_ERROR_MESSAGES.grant_not_suspended);
        expect(changes).toBe(1);
        expect(storage.listGrants).toHaveBeenCalledTimes(2);
        expect(actionLabels('Echo')).toEqual(['Suspend…']);
    });

    it("keeps a row's buttons waiting while its request is under way", () => {
        const answer = new Subject<PluginGrant>();
        storage.listGrants.mockReturnValue(of(page([SUSPENDED, ACTIVE])));
        storage.resumeGrant.mockReturnValue(answer);
        render();

        actionButton('Echo', 'Resume')!.click();
        refresh();
        expect(actionButton('Echo', 'Resume')!.disabled).toBe(true);
        expect(actionButton('Acme', 'Suspend…')!.disabled).toBe(false);

        const resumed: PluginGrant = { ...SUSPENDED, state: 'active', allowed_actions: ['suspend'] };
        storage.listGrants.mockReturnValue(of(page([resumed, ACTIVE])));
        answer.next(resumed);
        answer.complete();
        refresh();
        expect(actionButton('Echo', 'Suspend…')!.disabled).toBe(false);
    });

    it('keeps polling after an action while a grant still installs', () => {
        storage.listGrants.mockReturnValue(of(page([SUSPENDED, INSTALLING])));
        render();
        storage.listGrants.mockReturnValue(
            of(page([{ ...SUSPENDED, state: 'active', allowed_actions: ['suspend'] }, INSTALLING]))
        );

        actionButton('Echo', 'Resume')!.click();
        refresh();
        expect(storage.listGrants).toHaveBeenCalledTimes(2);

        poll();
        expect(storage.listGrants).toHaveBeenCalledTimes(3);
    });
});
