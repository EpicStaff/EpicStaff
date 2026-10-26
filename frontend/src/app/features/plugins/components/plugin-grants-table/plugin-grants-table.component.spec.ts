import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogData, ConfirmationDialogService } from '@shared/components';
import { Observable, of, Subject, throwError } from 'rxjs';
import type { Mock } from 'vitest';

import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { ToastService } from '../../../../services/notifications';
import { PluginGrant, PluginOrgRemovedJob, PluginState } from '../../models/plugin-admin.model';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildOrgRemovedJob, buildPluginGrant, buildUpgradeHook } from '../../testing/plugin-fixtures';
import { PLUGIN_ERROR_MESSAGES } from '../../utils/plugin-error-message.util';
import { PluginGrantPurgeTarget } from '../plugin-purge-dialog/plugin-purge-dialog.component';
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

/** Acme's data being deleted: Weather's hook waits for its next try after a failed first attempt. */
const DELETING = buildPluginGrant({
    state: 'purging',
    allowed_actions: [],
    purge_started_at: '2026-10-21T09:00:00Z',
    org_removed_hook: buildOrgRemovedJob({ error: 'Weather answered 500: database is locked' }),
});

/** Foxtrot's upgrade hook failed once; it is tried again by itself in a minute. */
const UPGRADING = buildPluginGrant({
    id: 10,
    organization: { id: 8, name: 'Foxtrot' },
    state: 'upgrading',
    allowed_actions: ['suspend', 'purge'],
    installed_version: '0.6.0',
    upgrade_hook: buildUpgradeHook(),
});
/** Golf's upgrade hook ran out of automatic retries. */
const UPGRADE_FAILED = buildPluginGrant({
    id: 11,
    organization: { id: 9, name: 'Golf' },
    state: 'upgrade_failed',
    allowed_actions: ['retry_upgrade', 'suspend', 'purge'],
    installed_version: '0.6.0',
    last_hook_error: 'The upgrade hook did not answer in time',
    upgrade_hook: buildUpgradeHook({
        state: 'failed',
        attempt: 3,
        next_attempt_at: null,
        finished_at: '2026-10-21T10:11:00Z',
        error: 'Weather answered HTTP 500.',
    }),
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
        retryHook: Mock<(identifier: string, grantId: number) => Observable<PluginGrant>>;
        resumeGrant: Mock<(identifier: string, grantId: number) => Observable<PluginGrant>>;
        retryOrgRemovedJob: Mock<(identifier: string, jobId: number) => Observable<PluginOrgRemovedJob>>;
        skipOrgRemovedJob: Mock<(identifier: string, jobId: number) => Observable<PluginOrgRemovedJob>>;
    };
    let openSuspend: Mock<(data: PluginSuspendDialogData) => Observable<PluginGrant | undefined>>;
    let openGrantPurge: Mock<(data: PluginGrantPurgeTarget) => Observable<PluginGrant | undefined>>;
    let confirm: Mock<(options: ConfirmationDialogData) => Observable<boolean | 'close'>>;
    let toast: { success: Mock; warning: Mock; error: Mock };
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

    function dataRemovalButton(organization: string, label: string): HTMLButtonElement | undefined {
        return Array.from(
            rowOf(organization).querySelectorAll<HTMLButtonElement>('app-plugin-data-removal-actions button')
        ).find((button) => button.textContent?.trim() === label);
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
            retryHook: vi.fn(() => of(installing(FAILED))),
            resumeGrant: vi.fn(() => of({ ...SUSPENDED, state: 'active' as const, allowed_actions: ['suspend'] })),
            retryOrgRemovedJob: vi.fn(() =>
                of(buildOrgRemovedJob({ next_attempt_at: null, allowed_actions: ['skip'] }))
            ),
            skipOrgRemovedJob: vi.fn(() => of(buildOrgRemovedJob({ state: 'skipped', allowed_actions: [] }))),
        };
        openSuspend = vi.fn(() => of<PluginGrant | undefined>(undefined));
        openGrantPurge = vi.fn(() => of<PluginGrant | undefined>(undefined));
        confirm = vi.fn(() => of<boolean | 'close'>(true));
        toast = { success: vi.fn(), warning: vi.fn(), error: vi.fn() };
        TestBed.configureTestingModule({
            imports: [PluginGrantsTableComponent],
            providers: [
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: PluginDialogsService, useValue: { openSuspend, openGrantPurge } },
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
        expect(cells('Acme')[3]).toBe('Created Oct 21, 2026 Key used 5m ago');
        expect(cells('Acme')[4]).toBe('2');
        expect(cells('Bravo')[3]).toBe('Created Oct 21, 2026 Key never used');
        expect(cells('Bravo')[4]).toBe('0');
        expect(cells('Delta')[3]).toBe('—');
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
        expect(storage.retryHook).not.toHaveBeenCalled();

        retryButton('Charlie')!.click();
        refresh();

        expect(confirm).toHaveBeenCalledTimes(2);
        expect(storage.retryHook).toHaveBeenCalledWith('weather', FAILED.id);
        expect(toast.success).toHaveBeenCalledWith('Weather is installing in Charlie again.');
        expect(rowOf('Charlie').textContent).toContain('Waiting for the plugin to start');
        expect(retryButton('Charlie')).toBeUndefined();
    });

    it('says why a retry was refused and shows the grant as it is now', () => {
        storage.listGrants.mockReturnValue(of(page([FAILED])));
        storage.retryHook.mockReturnValue(
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

    it('announces a state change with its badge or its progress line, not the whole cell', () => {
        storage.listGrants.mockReturnValue(of(page([ACTIVE, INSTALLING])));
        render();

        expect(rowOf('Bravo').querySelector('.grants__state')?.hasAttribute('aria-live')).toBe(false);
        expect(rowOf('Bravo').querySelector('.grants__installing')?.getAttribute('aria-live')).toBe('polite');
        expect(rowOf('Acme').querySelector('app-plugin-badge')?.getAttribute('aria-live')).toBe('polite');
    });

    describe('upgrades', () => {
        function cells(organization: string): (string | undefined)[] {
            return Array.from(rowOf(organization).querySelectorAll('.table-cell')).map((cell) =>
                cell.textContent?.replace(/\s+/g, ' ').trim()
            );
        }

        it('shows the version each organization was last brought to, and none before its install finished', () => {
            storage.listGrants.mockReturnValue(
                of(
                    page([
                        { ...ACTIVE, installed_version: '0.7.0' },
                        { ...INSTALLING, installed_version: null },
                    ])
                )
            );
            render();

            expect(element.querySelector('.table-header')?.textContent).toContain('Version');
            expect(cells('Acme')[2]).toBe('0.7.0');
            expect(cells('Bravo')[2]).toBe('—');
        });

        it('shows an upgrading organization with its attempt, its next try and the error of the last one', () => {
            storage.listGrants.mockReturnValue(of(page([UPGRADING])));
            render();

            const row = rowOf('Foxtrot');
            expect(row.querySelector('.grants__upgrading')?.textContent?.trim()).toBe('Upgrading…');
            expect(row.querySelector('app-spinner2')).not.toBeNull();
            expect(row.querySelector('.grants__upgrade-progress')?.textContent?.trim()).toMatch(
                /^Attempt 1 · next try \d{1,2}:\d{2}\s?[AP]M$/
            );
            expect(row.querySelector('.grants__upgrade-last-error')?.textContent?.trim()).toBe(
                'Last attempt failed: Weather answered HTTP 500.'
            );
            expect(cells('Foxtrot')[2]).toBe('0.6.0');
        });

        it('does not show an earlier upgrade’s hook as this one’s progress', () => {
            storage.listGrants.mockReturnValue(
                of(
                    page([
                        {
                            ...UPGRADING,
                            upgrade_hook: buildUpgradeHook({
                                state: 'succeeded',
                                from_version: '0.5.0',
                                next_attempt_at: null,
                                error: null,
                            }),
                        },
                        { ...UPGRADING, id: 12, organization: { id: 10, name: 'Hotel' }, upgrade_hook: null },
                    ])
                )
            );
            render();

            for (const organization of ['Foxtrot', 'Hotel']) {
                expect(rowOf(organization).querySelector('.grants__upgrade-progress')?.textContent?.trim()).toBe(
                    'Waiting for the new version to start'
                );
                expect(rowOf(organization).querySelector('.grants__upgrade-last-error')).toBeNull();
            }
        });

        it('says when the upgrade hook runs, and when it waits for the plugin to claim it', () => {
            storage.listGrants.mockReturnValue(
                of(
                    page([
                        { ...UPGRADING, upgrade_hook: buildUpgradeHook({ state: 'running', attempt: 1, error: null }) },
                        {
                            ...UPGRADING,
                            id: 12,
                            organization: { id: 10, name: 'Hotel' },
                            upgrade_hook: buildUpgradeHook({ attempt: 0, next_attempt_at: null, error: null }),
                        },
                    ])
                )
            );
            render();

            expect(rowOf('Foxtrot').querySelector('.grants__upgrade-progress')?.textContent?.trim()).toBe(
                'Running its upgrade'
            );
            expect(rowOf('Hotel').querySelector('.grants__upgrade-progress')?.textContent?.trim()).toBe(
                'Waiting for the plugin to start'
            );
        });

        it('shows a failed upgrade with its error and Retry upgrade from the actions it allows', () => {
            storage.listGrants.mockReturnValue(of(page([UPGRADE_FAILED])));
            render();

            const row = rowOf('Golf');
            expect(row.querySelector('app-plugin-badge')?.textContent?.trim()).toBe('Upgrade failed');
            expect(row.querySelector('.grants__upgrade-error')?.textContent?.trim()).toBe('Weather answered HTTP 500.');
            expect(actionLabels('Golf')).toEqual(['Retry upgrade', 'Suspend…', 'Delete data…']);
        });

        it("falls back to the grant's copy of the hook error when the job has none", () => {
            storage.listGrants.mockReturnValue(of(page([{ ...UPGRADE_FAILED, upgrade_hook: null }])));
            render();

            expect(rowOf('Golf').querySelector('.grants__upgrade-error')?.textContent?.trim()).toBe(
                'The upgrade hook did not answer in time'
            );
        });

        it('retries a failed upgrade only after confirmation, then shows it upgrading', () => {
            storage.listGrants.mockReturnValue(of(page([UPGRADE_FAILED])));
            storage.retryHook.mockReturnValue(
                of({ ...UPGRADE_FAILED, state: 'upgrading', allowed_actions: ['suspend', 'purge'] })
            );
            render();
            storage.listGrants.mockReturnValue(of(page([UPGRADING])));

            confirm.mockReturnValueOnce(of(false));
            actionButton('Golf', 'Retry upgrade')!.click();
            expect(storage.retryHook).not.toHaveBeenCalled();

            actionButton('Golf', 'Retry upgrade')!.click();
            refresh();

            expect(confirm).toHaveBeenLastCalledWith(
                expect.objectContaining({
                    message: 'Weather runs its upgrade hook in Golf again.',
                    confirmText: 'Retry upgrade',
                })
            );
            expect(storage.retryHook).toHaveBeenCalledWith('weather', UPGRADE_FAILED.id);
            expect(toast.success).toHaveBeenCalledWith('Weather is upgrading in Golf again.');
            expect(changes).toBe(0);
        });

        it('polls while an organization is upgrading, and stops once none is', () => {
            storage.listGrants.mockReturnValue(of(page([UPGRADING])));
            render();

            storage.listGrants.mockReturnValue(
                of(page([{ ...UPGRADING, state: 'active', installed_version: '0.7.0' }]))
            );
            poll();
            poll();

            expect(storage.listGrants).toHaveBeenCalledTimes(2);
            expect(changes).toBe(1);
        });
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

        expect(actionLabels('Acme')).toEqual(['Suspend…', 'Delete data…']);
        expect(actionLabels('Charlie')).toEqual(['Retry install', 'Suspend…']);
        expect(actionLabels('Echo')).toEqual(['Resume']);
        expect(actionLabels('Delta')).toEqual([]);
        expect(actionLabels('Foxtrot')).toEqual(['Resume']);
        expect(element.querySelector('.table-header')?.textContent).toContain('Actions');
    });

    it('leaves out an action this page does not know', () => {
        const unknownAction = { ...ACTIVE, allowed_actions: ['transfer', 'suspend'] } as unknown as PluginGrant;
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

    it('warns that the install has not finished when a resumed grant comes back with its install failed', () => {
        const resumedFailed: PluginGrant = {
            ...SUSPENDED,
            state: 'install_failed',
            allowed_actions: ['retry_install', 'suspend'],
            suspended_at: null,
            purge_after: null,
        };
        storage.listGrants.mockReturnValue(of(page([SUSPENDED])));
        storage.resumeGrant.mockReturnValue(of(resumedFailed));
        render();
        storage.listGrants.mockReturnValue(of(page([resumedFailed])));

        actionButton('Echo', 'Resume')!.click();
        refresh();

        expect(toast.warning).toHaveBeenCalledWith(
            'Weather is resumed in Echo; its install has not finished. Retry it.'
        );
        expect(toast.success).not.toHaveBeenCalled();
        expect(actionLabels('Echo')).toEqual(['Retry install', 'Suspend…']);
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
    it('says a grant was suspended by the uninstall of the plugin', () => {
        storage.listGrants.mockReturnValue(of(page([{ ...SUSPENDED, suspension_cause: 'uninstall' }])));
        render();

        expect(rowOf('Echo').querySelector('app-plugin-badge')?.textContent?.trim()).toBe(
            'Suspended (plugin uninstalled)'
        );
    });

    it('opens the data deletion preview, and once deleting shows the row, tells the page and reloads', () => {
        openGrantPurge.mockReturnValue(of(DELETING));
        storage.listGrants.mockReturnValue(of(page([ACTIVE])));
        render();
        storage.listGrants.mockReturnValue(of(page([DELETING])));

        actionButton('Acme', 'Delete data…')!.click();
        refresh();

        expect(openGrantPurge).toHaveBeenCalledWith({ identifier: 'weather', pluginName: 'Weather', grant: ACTIVE });
        expect(confirm).not.toHaveBeenCalled();
        expect(toast.success).toHaveBeenCalledWith("Deleting Weather's data in Acme.");
        expect(changes).toBe(1);
        expect(storage.listGrants).toHaveBeenCalledTimes(2);
        expect(rowOf('Acme').textContent).toContain('Deleting data…');
        expect(actionLabels('Acme')).toEqual([]);
    });

    it('reloads after the data deletion preview is cancelled, and says nothing', () => {
        storage.listGrants.mockReturnValue(of(page([ACTIVE])));
        render();

        actionButton('Acme', 'Delete data…')!.click();
        refresh();

        expect(toast.success).not.toHaveBeenCalled();
        expect(changes).toBe(0);
        expect(storage.listGrants).toHaveBeenCalledTimes(2);
    });

    it("shows a deleting row with where the plugin is with its own data, its attempt and next try, and the job's buttons", () => {
        storage.listGrants.mockReturnValue(of(page([DELETING])));
        render();

        const row = rowOf('Acme');
        expect(row.querySelector('.grants__deleting')?.textContent?.trim()).toBe('Deleting data…');
        expect(row.querySelector('.grants__data-removal')?.textContent?.trim()).toBe('Weather is deleting its data');
        expect(row.querySelector('.grants__data-removal')?.hasAttribute('tabindex')).toBe(false);
        expect(row.querySelector('.grants__data-removal-progress')?.textContent?.trim()).toMatch(
            /^Attempt 1 · next try \d{1,2}:\d{2}\s?[AP]M$/
        );
        expect(row.querySelector('.grants__data-removal-last-error')?.textContent?.trim()).toBe(
            'Last attempt failed: Weather answered 500: database is locked'
        );
        expect(
            Array.from(row.querySelectorAll('app-plugin-data-removal-actions button')).map((button) =>
                button.textContent?.trim()
            )
        ).toEqual(['Retry', 'Skip']);
        expect(row.querySelector('.grants__purge-error')).toBeNull();
    });

    it('says the plugin could not delete its data, and what EpicStaff could not delete yet', () => {
        const failed: PluginGrant = {
            ...DELETING,
            last_purge_error: 'Flow "Daily digest" is linked to another organization',
            org_removed_hook: buildOrgRemovedJob({
                state: 'failed',
                attempt: 9,
                next_attempt_at: null,
                finished_at: '2026-10-28T09:00:00Z',
                error: 'Weather answered 500: database is locked',
            }),
        };
        storage.listGrants.mockReturnValue(of(page([failed])));
        render();

        const row = rowOf('Acme');
        expect(row.querySelector('.grants__data-removal')?.textContent?.trim()).toBe(
            'Weather could not delete its data: Weather answered 500: database is locked'
        );
        expect(row.querySelector('.grants__data-removal')?.classList).toContain('grants__hook-error');
        expect(row.querySelector('.grants__data-removal')?.getAttribute('tabindex')).toBe('0');
        expect(row.querySelector('.grants__data-removal-progress')).toBeNull();
        expect(row.querySelector('.grants__purge-error')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
            'Some resources could not be deleted yet: Flow "Daily digest" is linked to another organization; ' +
                'EpicStaff retries every hour'
        );
    });

    it('shows no data removal line once the plugin has deleted its data, or for a plugin without a hook', () => {
        storage.listGrants.mockReturnValue(
            of(
                page([
                    { ...DELETING, org_removed_hook: buildOrgRemovedJob({ state: 'succeeded', allowed_actions: [] }) },
                    { ...DELETING, id: 6, organization: { id: 4, name: 'Bravo' }, org_removed_hook: null },
                ])
            )
        );
        render();

        expect(rowOf('Acme').querySelector('.grants__data-removal')).toBeNull();
        expect(rowOf('Bravo').querySelector('.grants__data-removal')).toBeNull();
        expect(rowOf('Acme').textContent).toContain('Deleting data…');
    });

    it('retries a data removal at once, and reloads', () => {
        storage.listGrants.mockReturnValue(of(page([DELETING])));
        render();

        dataRemovalButton('Acme', 'Retry')!.click();
        refresh();

        expect(confirm).not.toHaveBeenCalled();
        expect(storage.retryOrgRemovedJob).toHaveBeenCalledWith('weather', DELETING.org_removed_hook!.id);
        expect(toast.success).toHaveBeenCalledWith('Weather tries again to delete its data for Acme.');
        expect(storage.listGrants).toHaveBeenCalledTimes(2);
    });

    it('skips a data removal only after confirmation, and reloads', () => {
        storage.listGrants.mockReturnValue(of(page([DELETING])));
        render();

        confirm.mockReturnValueOnce(of(false));
        dataRemovalButton('Acme', 'Skip')!.click();
        refresh();
        expect(storage.skipOrgRemovedJob).not.toHaveBeenCalled();
        expect(storage.listGrants).toHaveBeenCalledTimes(1);

        dataRemovalButton('Acme', 'Skip')!.click();
        refresh();

        expect(confirm).toHaveBeenLastCalledWith(
            expect.objectContaining({
                message: "Skip? Weather's data for Acme then stays where Weather keeps it until Weather is deleted.",
                confirmText: 'Skip',
            })
        );
        expect(storage.skipOrgRemovedJob).toHaveBeenCalledWith('weather', DELETING.org_removed_hook!.id);
        expect(storage.listGrants).toHaveBeenCalledTimes(2);
    });

    it('says why a data removal action was refused, and shows the row as it is now', () => {
        storage.retryOrgRemovedJob.mockReturnValue(throwError(() => conflict('org_removed_hook_not_retryable')));
        storage.listGrants.mockReturnValue(of(page([DELETING])));
        render();

        dataRemovalButton('Acme', 'Retry')!.click();
        refresh();

        expect(toast.error).toHaveBeenCalledWith(PLUGIN_ERROR_MESSAGES.org_removed_hook_not_retryable);
        expect(storage.listGrants).toHaveBeenCalledTimes(2);
    });

    it('polls while a row deletes its data, and tells the page once the row is gone', () => {
        storage.listGrants.mockReturnValue(
            of(page([ACTIVE, { ...DELETING, id: 6, organization: { id: 4, name: 'Bravo' } }]))
        );
        render();

        poll();
        expect(storage.listGrants).toHaveBeenCalledTimes(2);
        expect(changes).toBe(0);

        storage.listGrants.mockReturnValue(of(page([ACTIVE])));
        poll();
        expect(storage.listGrants).toHaveBeenCalledTimes(3);
        expect(changes).toBe(1);

        poll();
        expect(storage.listGrants).toHaveBeenCalledTimes(3);
    });

    it("loads the grants again when the plugin's state changes, since what each grant allows depends on it", () => {
        storage.listGrants.mockReturnValue(of(page([ACTIVE])));
        render();
        fixture.componentRef.setInput('pluginState', 'running' satisfies PluginState);
        refresh();
        const loads = storage.listGrants.mock.calls.length;

        storage.listGrants.mockReturnValue(of(page([{ ...ACTIVE, allowed_actions: ['purge'] }])));
        fixture.componentRef.setInput('pluginState', 'uninstalling' satisfies PluginState);
        refresh();

        expect(storage.listGrants).toHaveBeenCalledTimes(loads + 1);
        expect(actionLabels('Acme')).toEqual(['Delete data…']);
    });
});
