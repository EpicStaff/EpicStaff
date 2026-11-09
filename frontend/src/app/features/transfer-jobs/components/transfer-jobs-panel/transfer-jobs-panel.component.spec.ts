import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { isUnfinishedTransferJob, TransferJob } from '../../../../core/models/transfer-job.model';
import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ConfigService } from '../../../../services/config';
import { TransferJobsPanelComponent } from './transfer-jobs-panel.component';

const LIST_URL = '/api/transfer-jobs/';

function job(overrides: Partial<TransferJob>): TransferJob {
    return {
        id: 'job-1',
        kind: 'export',
        main_entity: 'Flow',
        status: 'completed',
        display_name: 'Orders',
        file_name: 'Orders.zip',
        result: { excluded: [] },
        error: null,
        created_at: '2026-11-06T10:00:00Z',
        finished_at: '2026-11-06T10:01:00Z',
        expires_at: '2026-11-13T10:01:00Z',
        ...overrides,
    } as TransferJob;
}

const READY_EXPORT = job({ id: 'ready', display_name: 'Orders' });
const RUNNING_EXPORT = job({
    id: 'running',
    status: 'running',
    display_name: '3 tools',
    main_entity: 'PythonCodeTool',
    file_name: null,
    result: null,
    finished_at: null,
    expires_at: null,
});
const REMOVED_EXPORT = job({
    id: 'removed',
    display_name: 'Old sessions',
    main_entity: 'Session',
    error: { code: 'archive_removed', message: 'The archive was removed to make room for newer exports.' },
});
const FAILED_IMPORT = job({
    id: 'failed',
    kind: 'import',
    status: 'failed',
    display_name: 'handbook.zip',
    main_entity: 'SourceCollection',
    result: null,
    error: { code: 'import_failed', message: 'The archive is damaged.' },
});

// jsdom has no ResizeObserver; the buttons' collapse-on-overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('TransferJobsPanelComponent', () => {
    let fixture: ComponentFixture<TransferJobsPanelComponent>;
    let element: HTMLElement;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
        TestBed.configureTestingModule({
            imports: [TransferJobsPanelComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                { provide: ProfileService, useValue: { currentUserSignal: signal({ id: 1 }) } },
                { provide: ActiveOrgService, useValue: { activeOrgId: signal(7) } },
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
        fixture = TestBed.createComponent(TransferJobsPanelComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
        TestBed.tick();
    });

    afterEach(() => {
        httpMock.verify();
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    function pendingListRequests(): TestRequest[] {
        return httpMock
            .match((request) => request.url === LIST_URL && request.method === 'GET')
            .filter((request) => !request.cancelled);
    }

    /**
     * Answers every pending request for the list as a server holding `jobs`, newest first, would: the slice the
     * request's limit and offset ask for (50 from the start by default), of the jobs its status filter keeps. Taken
     * out of the testing controller, a request read beforehand is passed in to be answered.
     */
    function answerFromServer(jobs: TransferJob[], requests: TestRequest[] = pendingListRequests()): void {
        for (const request of requests) {
            const params = request.request.params;
            const matching = params.has('status') ? jobs.filter(isUnfinishedTransferJob) : jobs;
            const offset = Number(params.get('offset') ?? 0);
            const limit = Number(params.get('limit') ?? 50);
            request.flush({ count: matching.length, results: matching.slice(offset, offset + limit) });
        }
        fixture.detectChanges();
    }

    /** The panel and the store both ask for the list when it opens; the last request is the one that counts. */
    function answerList(...jobs: TransferJob[]): void {
        answerFromServer(jobs);
    }

    /** Finished exports named "Job 1" (the newest) to "Job <count>". */
    function finishedJobs(count: number): TransferJob[] {
        return Array.from({ length: count }, (_, index) =>
            job({ id: `job-${index + 1}`, display_name: `Job ${index + 1}` })
        );
    }

    function names(): string[] {
        return rows().map((listed) => listed.querySelector('.transfer-jobs-panel__name')?.textContent?.trim() ?? '');
    }

    function namesOf(jobs: TransferJob[]): string[] {
        return jobs.map((listed) => listed.display_name ?? '');
    }

    function moreButton(): HTMLButtonElement | null {
        return element.querySelector<HTMLButtonElement>('[data-test="transfer-jobs-more"] button');
    }

    function rows(): HTMLElement[] {
        return Array.from(element.querySelectorAll<HTMLElement>('[data-test="transfer-job"]'));
    }

    function row(name: string): HTMLElement {
        const found = rows().find((candidate) => candidate.textContent?.includes(name));
        if (!found) throw new Error(`No row for ${name}`);
        return found;
    }

    function button(within: HTMLElement, label: string): HTMLButtonElement | null {
        return within.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
    }

    function deleteRequest(id: string): TestRequest {
        return httpMock.expectOne(
            (request) => request.url === `/api/transfer-jobs/${id}/` && request.method === 'DELETE'
        );
    }

    it('lists each job with what it is, its status and the reason it failed', () => {
        answerList(RUNNING_EXPORT, READY_EXPORT, FAILED_IMPORT);

        expect(rows().map((listed) => listed.querySelector('.transfer-jobs-panel__name')?.textContent?.trim())).toEqual(
            ['3 tools', 'Orders', 'handbook.zip']
        );
        expect(row('3 tools').textContent).toContain('Export · Custom tools');
        expect(row('3 tools').querySelector('[data-test="transfer-job-status"]')?.textContent?.trim()).toBe('Running');
        expect(row('3 tools').querySelector('.transfer-jobs-panel__spinner')).not.toBeNull();
        expect(row('Orders').querySelector('.transfer-jobs-panel__spinner')).toBeNull();
        expect(row('handbook.zip').textContent).toContain('Import · Knowledge collections');
        expect(row('handbook.zip').querySelector('[data-test="transfer-job-error"]')?.textContent?.trim()).toBe(
            'The archive is damaged.'
        );
    });

    describe('paging', () => {
        function pageParams(request: TestRequest): [string | null, string | null] {
            return [request.request.params.get('limit'), request.request.params.get('offset')];
        }

        it('asks for the newest ten jobs first', () => {
            const requests = pendingListRequests();
            const pages = requests.filter((request) => !request.request.params.has('status'));

            expect(pages.length).toBeGreaterThan(0);
            expect(pages.map(pageParams)).toEqual(pages.map(() => ['10', null]));
            answerFromServer([], requests);
        });

        it('offers no more when every job is listed', () => {
            answerFromServer(finishedJobs(10));

            expect(rows()).toHaveLength(10);
            expect(moreButton()).toBeNull();
        });

        it('adds the next ten older jobs after the listed ones', () => {
            const server = finishedJobs(23);
            answerFromServer(server);
            expect(names()).toEqual(namesOf(server.slice(0, 10)));
            expect(moreButton()?.textContent?.trim()).toBe('Show more (13 left)');

            moreButton()!.click();
            const requests = pendingListRequests();
            expect(requests.map(pageParams)).toEqual([['10', '10']]);
            answerFromServer(server, requests);

            expect(names()).toEqual(namesOf(server.slice(0, 20)));
            expect(moreButton()?.textContent?.trim()).toBe('Show more (3 left)');
        });

        it('shows that the next page is loading and ignores clicks meanwhile', () => {
            const server = finishedJobs(12);
            answerFromServer(server);

            moreButton()!.click();
            fixture.detectChanges();
            moreButton()!.click();

            expect(moreButton()?.textContent?.trim()).toBe('Loading…');
            expect(moreButton()?.getAttribute('aria-disabled')).toBe('true');
            const requests = pendingListRequests();
            expect(requests).toHaveLength(1);
            answerFromServer(server, requests);
        });

        it('lists each job once when a new job pushed the older ones down meanwhile', () => {
            answerFromServer(finishedJobs(12));
            const withNewJob = [job({ id: 'new', display_name: 'New job' }), ...finishedJobs(12)];

            moreButton()!.click();
            // The page at offset 10 now starts with Job 10, which is listed already.
            answerFromServer(withNewJob);
            expect(names()).toEqual(namesOf(finishedJobs(12)));

            // The list is loaded again, which brings the new job in at its top.
            answerFromServer(withNewJob);
            expect(names()).toEqual(namesOf(withNewJob));
            expect(moreButton()).toBeNull();
        });

        it('offers to try again when the next page could not be loaded', () => {
            const server = finishedJobs(12);
            answerFromServer(server);

            moreButton()!.click();
            pendingListRequests().forEach((request) => request.flush({}, { status: 500, statusText: 'Server Error' }));
            fixture.detectChanges();

            expect(element.querySelector('[role="alert"]')?.textContent?.trim()).toBe('Could not load more.');
            expect(moreButton()?.textContent?.trim()).toBe('Try again');
            expect(rows()).toHaveLength(10);
            moreButton()!.click();
            answerFromServer(server);

            expect(names()).toEqual(namesOf(server));
            expect(element.querySelector('[role="alert"]')).toBeNull();
        });

        it('keeps paging from the right place after a job of a later page is cleared', () => {
            let server = finishedJobs(25);
            answerFromServer(server);
            moreButton()!.click();
            answerFromServer(server);

            button(row('Job 15'), 'Clear Job 15')!.click();
            deleteRequest('job-15').flush(null, { status: 204, statusText: 'No Content' });
            server = server.filter((listed) => listed.id !== 'job-15');
            fixture.detectChanges();

            expect(names()).not.toContain('Job 15');
            expect(moreButton()?.textContent?.trim()).toBe('Show more (5 left)');
            moreButton()!.click();
            const requests = pendingListRequests();
            expect(requests.map(pageParams)).toEqual([['10', '19']]);
            answerFromServer(server, requests);

            expect(names()).toEqual(namesOf(server));
        });

        it('moves the focus to the first job of the last page, as the button it was on goes away', async () => {
            const server = finishedJobs(12);
            answerFromServer(server);

            moreButton()!.focus();
            moreButton()!.click();
            answerFromServer(server);
            await fixture.whenStable();

            expect(document.activeElement).toBe(row('Job 11'));
        });
    });

    it('says when there are no jobs', () => {
        answerList();

        expect(rows()).toEqual([]);
        expect(element.textContent).toContain('No exports or imports yet.');
    });

    it('offers Download only for a completed export whose archive is still kept', () => {
        answerList(RUNNING_EXPORT, READY_EXPORT, REMOVED_EXPORT, FAILED_IMPORT);

        expect(button(row('Orders'), 'Download Orders')).not.toBeNull();
        expect(button(row('3 tools'), 'Download 3 tools')).toBeNull();
        expect(button(row('Old sessions'), 'Download Old sessions')).toBeNull();
        expect(row('Old sessions').textContent).toContain('The archive was removed to make room for newer exports.');
        expect(button(row('handbook.zip'), 'Download handbook.zip')).toBeNull();
    });

    it('downloads the archive of the export the user picked', () => {
        answerList(READY_EXPORT);

        button(row('Orders'), 'Download Orders')!.click();

        httpMock
            .expectOne('/api/transfer-jobs/ready/download-ticket/')
            .flush({ download_url: '/api/transfer-jobs/ready/download/?ticket=t-1' });
    });

    it('clears a finished job and drops it from the list', () => {
        answerList(READY_EXPORT, FAILED_IMPORT);

        button(row('handbook.zip'), 'Clear handbook.zip')!.click();
        deleteRequest('failed').flush(null, { status: 204, statusText: 'No Content' });
        fixture.detectChanges();

        expect(rows().map((listed) => listed.querySelector('.transfer-jobs-panel__name')?.textContent?.trim())).toEqual(
            ['Orders']
        );
    });

    it('puts the actions of a job side by side in one group, apart from its text', () => {
        answerList(READY_EXPORT);

        const actions = row('Orders').querySelector('[data-test="transfer-job-actions"]');
        expect(
            Array.from(actions?.children ?? []).map((action) => [action.tagName, action.getAttribute('aria-label')])
        ).toEqual([
            ['BUTTON', 'Download Orders'],
            ['BUTTON', 'Clear Orders'],
        ]);
        expect(actions?.textContent?.trim()).toBe('');
        expect(
            row('Orders')
                .querySelector('.transfer-jobs-panel__item-main')
                ?.contains(actions ?? null)
        ).toBe(false);
    });

    it('keeps Clear inactive while a job is running', () => {
        answerList(RUNNING_EXPORT, READY_EXPORT);

        expect(button(row('3 tools'), 'Clear 3 tools')!.getAttribute('aria-disabled')).toBe('true');
        expect(button(row('Orders'), 'Clear Orders')!.hasAttribute('aria-disabled')).toBe(false);

        button(row('3 tools'), 'Clear 3 tools')!.click();
        httpMock.expectNone((request) => request.method === 'DELETE');
    });

    describe('Clear all', () => {
        function clearAllButton(): HTMLButtonElement {
            return element.querySelector<HTMLButtonElement>('[data-test="transfer-jobs-clear-all"] button')!;
        }

        function confirmationDialog(): HTMLElement | null {
            return document.querySelector<HTMLElement>('.dialog-container');
        }

        function clickDialogButton(selector: '.confirm-button' | '.cancel-button'): void {
            confirmationDialog()!.querySelector<HTMLButtonElement>(selector)!.click();
            fixture.detectChanges();
        }

        function expectClearRequest(): TestRequest {
            return httpMock.expectOne(
                (request) => request.url === '/api/transfer-jobs/clear/' && request.method === 'POST'
            );
        }

        it('asks first, saying what goes and that finished exports cannot be downloaded afterwards', () => {
            answerList(RUNNING_EXPORT, READY_EXPORT);

            clearAllButton().click();
            fixture.detectChanges();

            expect(confirmationDialog()!.querySelector('.dialog-title')!.textContent!.trim()).toBe('Clear all jobs?');
            expect(confirmationDialog()!.querySelector('.dialog-message')!.textContent!.trim()).toBe(
                "Removes all your export and import jobs except running ones. Finished exports can't be downloaded " +
                    'afterwards.'
            );
            expect(confirmationDialog()!.querySelector('.confirm-button')!.textContent!.trim()).toBe('Clear all');
            httpMock.expectNone((request) => request.method === 'POST');
        });

        it('clears once confirmed and lists the running jobs the server kept', () => {
            answerList(RUNNING_EXPORT, READY_EXPORT, FAILED_IMPORT);

            clearAllButton().click();
            fixture.detectChanges();
            clickDialogButton('.confirm-button');
            expectClearRequest().flush({ deleted: 2 });
            answerList(RUNNING_EXPORT);

            expect(names()).toEqual(['3 tools']);
        });

        it('sends nothing when the user cancels', () => {
            answerList(READY_EXPORT);

            clearAllButton().click();
            fixture.detectChanges();
            clickDialogButton('.cancel-button');

            httpMock.expectNone((request) => request.method === 'POST');
            expect(confirmationDialog()).toBeNull();
            expect(names()).toEqual(['Orders']);
        });

        /** The hint keyboard focus shows on the button, as after a Tab; undefined for none. */
        async function clearAllHintOnKeyboardFocus(): Promise<string | undefined> {
            document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', keyCode: 9, bubbles: true }));
            clearAllButton().focus();
            TestBed.tick();
            // The tooltip shows after a zero delay.
            await new Promise((resolve) => setTimeout(resolve));
            TestBed.tick();
            return document.querySelector('.mat-mdc-tooltip')?.textContent?.trim();
        }

        /** Off, yet focusable: it keeps the focus it holds, and its hint stays reachable by keyboard. */
        function expectOff(): void {
            expect(clearAllButton().getAttribute('aria-disabled')).toBe('true');
            expect(clearAllButton().disabled).toBe(false);
        }

        it.each([
            { case: 'there are no jobs', jobs: [], off: true, hint: 'There are no jobs to clear.' },
            {
                case: 'every job is running',
                jobs: [RUNNING_EXPORT],
                off: true,
                hint: 'Running jobs cannot be cleared. Wait for them to finish.',
            },
            { case: 'a job has finished', jobs: [RUNNING_EXPORT, FAILED_IMPORT], off: false, hint: undefined },
        ])('is off when $case: $off', async ({ jobs, off, hint }) => {
            answerList(...jobs);

            if (off) {
                expectOff();
            } else {
                expect(clearAllButton().hasAttribute('aria-disabled')).toBe(false);
            }
            expect(await clearAllHintOnKeyboardFocus()).toBe(hint);
        });

        it('is off while the jobs load, without saying there are none, and ignores a click', async () => {
            expectOff();
            expect(await clearAllHintOnKeyboardFocus()).toBe('Loading the jobs…');

            clearAllButton().click();
            fixture.detectChanges();
            expect(confirmationDialog()).toBeNull();

            answerList(READY_EXPORT);
            expect(clearAllButton().hasAttribute('aria-disabled')).toBe(false);
        });

        it('is off when the jobs could not be loaded, without saying there are none', async () => {
            pendingListRequests().forEach((request) => {
                if (!request.cancelled) {
                    request.flush({}, { status: 500, statusText: 'Server Error' });
                }
            });
            fixture.detectChanges();

            expectOff();
            expect(await clearAllHintOnKeyboardFocus()).toBe('The jobs could not be loaded.');
        });
    });

    it('offers to try again when the jobs could not be loaded', () => {
        const requests = httpMock.match((request) => request.url === LIST_URL);
        // A failed load cancels the other request of the same load.
        requests
            .filter((request) => !request.cancelled)
            .forEach((request) => {
                if (!request.cancelled) {
                    request.flush({}, { status: 500, statusText: 'Server Error' });
                }
            });
        fixture.detectChanges();

        expect(element.textContent).toContain('Could not load your exports and imports.');
        (
            Array.from(element.querySelectorAll('button')).find((candidate) =>
                candidate.textContent?.includes('Try again')
            ) as HTMLButtonElement
        ).click();
        answerList(READY_EXPORT);

        expect(rows()).toHaveLength(1);
    });
});
