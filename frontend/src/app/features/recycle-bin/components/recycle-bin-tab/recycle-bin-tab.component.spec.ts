import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import {
    ConfirmationDialogData,
    ConfirmationDialogService,
    ConfirmationResult,
    SearchComponent,
    SelectComponent,
} from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { Observable, of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { RecycleBinSettingsService } from '../../../../services/recycle-bin';
import { GetRecycleBinDetailResponse, RecycleBinTabKey } from '../../models/recycle-bin.model';
import { RecycleBinTableComponent } from '../recycle-bin-table/recycle-bin-table.component';
import { RecycleBinTabComponent } from './recycle-bin-tab.component';

const API_URL = 'http://api/';
const FLOWS_BIN = `${API_URL}graphs/recycle-bin/`;

/** The first page of a bin, newest first, plus any other query parameters in the order they are sent. */
function listUrl(bin: string, query = ''): string {
    return `${bin}?limit=50&offset=0&ordering=-deleted_at${query}`;
}

const FLOWS_LIST = listUrl(FLOWS_BIN);
const FILES_LIST = listUrl(`${API_URL}storage/recycle-bin/`);

const ROW_RESTORE = '.table-row app-activate-button button';
const ROW_DELETE = '.table-row app-delete-button button';
const RESTORE_SELECTED = '.bin-toolbar__restore-selected button';
const DELETE_SELECTED = '.bin-toolbar__delete-selected button';

function entry(
    id: number,
    name: string,
    overrides: { deleted_at?: string; days_left?: number; details?: GetRecycleBinDetailResponse[] } = {}
) {
    return {
        id,
        name,
        deleted_at: '2026-10-01T10:00:00Z',
        days_left: 5,
        details: [] as GetRecycleBinDetailResponse[],
        contents: [] as { name: string; kind: string }[],
        contents_total: 0,
        ...overrides,
    };
}

function storageEntry(id: number, path: string) {
    return { ...entry(id, path), item_type: path.endsWith('/') ? 'folder' : 'file' };
}

function page<Entry>(results: Entry[], count = results.length) {
    return { count, next: null, previous: null, results };
}

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('RecycleBinTabComponent', () => {
    let fixture: ComponentFixture<RecycleBinTabComponent>;
    let httpTesting: HttpTestingController;
    let grants: [ResourceCode, ActionCode][];
    let superadmin: WritableSignal<boolean>;
    let toast: { success: ReturnType<typeof vi.fn>; error: ReturnType<typeof vi.fn> };
    let confirm: ReturnType<typeof vi.fn<(options: ConfirmationDialogData) => Observable<ConfirmationResult>>>;

    beforeEach(() => {
        grants = [];
        superadmin = signal(false);
        toast = { success: vi.fn(), error: vi.fn() };
        confirm = vi.fn(() => of<ConfirmationResult>(true));
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } },
                {
                    provide: PermissionsService,
                    useValue: {
                        // Like the real service: a superadmin can do everything.
                        can: (resource: ResourceCode, action: ActionCode) =>
                            superadmin() ||
                            grants.some(
                                ([grantedResource, grantedAction]) =>
                                    grantedResource === resource && grantedAction === action
                            ),
                        get isSuperadmin(): boolean {
                            return superadmin();
                        },
                    },
                },
                { provide: ToastService, useValue: toast },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                { provide: RecycleBinSettingsService, useValue: { retentionDays: signal(7) } },
            ],
        });
        httpTesting = TestBed.inject(HttpTestingController);
    });

    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));

    afterEach(() => {
        httpTesting.verify();
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    function grant(resource: ResourceCode, ...actions: ActionCode[]): void {
        grants = [
            [resource, ActionCode.Read],
            ...actions.map((action): [ResourceCode, ActionCode] => [resource, action]),
        ];
    }

    function open(tab: RecycleBinTabKey): HTMLElement {
        fixture = TestBed.createComponent(RecycleBinTabComponent);
        fixture.componentRef.setInput('recycleBinTab', tab);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    function openFlowsWith(entries: ReturnType<typeof entry>[]): HTMLElement {
        const element = open('flows');
        httpTesting.expectOne(FLOWS_LIST).flush(page(entries));
        fixture.detectChanges();
        return element;
    }

    function click(element: HTMLElement, selector: string): void {
        element.querySelector<HTMLElement>(selector)?.click();
        fixture.detectChanges();
    }

    function rowNames(element: HTMLElement): string[] {
        return Array.from(element.querySelectorAll('.bin-name-text'), (cell) => cell.textContent?.trim() ?? '');
    }

    function checkRow(element: HTMLElement, index: number): void {
        element.querySelectorAll<HTMLInputElement>('.table-row app-checkbox input')[index].click();
        fixture.detectChanges();
    }

    function search(term: string): void {
        fixture.debugElement.query(By.directive(SearchComponent)).componentInstance.searchTerm.set(term);
        fixture.detectChanges();
    }

    function lastConfirm(): ConfirmationDialogData {
        return confirm.mock.calls.at(-1)![0];
    }

    describe('permissions', () => {
        it('shows no buttons or checkboxes with READ only', () => {
            grant(ResourceCode.Flows);
            const element = openFlowsWith([entry(5, 'Report')]);
            expect(element.querySelector('app-activate-button')).toBeNull();
            expect(element.querySelector('app-delete-button')).toBeNull();
            expect(element.querySelector('app-checkbox')).toBeNull();
        });

        it('offers only the restore actions with CREATE', () => {
            grant(ResourceCode.Flows, ActionCode.Create);
            const element = openFlowsWith([entry(5, 'Report')]);
            expect(element.querySelector(ROW_DELETE)).toBeNull();

            checkRow(element, 0);

            expect(element.querySelector(RESTORE_SELECTED)).not.toBeNull();
            expect(element.querySelector(DELETE_SELECTED)).toBeNull();
        });

        it('offers no delete-forever action with DELETE alone: that is superadmin-only', () => {
            grant(ResourceCode.Flows, ActionCode.Delete);
            const element = openFlowsWith([entry(5, 'Report')]);
            expect(element.querySelector('app-delete-button')).toBeNull();
            expect(element.querySelector('app-activate-button')).toBeNull();
            expect(element.querySelector('app-checkbox')).toBeNull();
        });

        it('shows the delete-forever action once the user turns superadmin, with no reload', () => {
            grant(ResourceCode.Flows, ActionCode.Create);
            const element = openFlowsWith([entry(5, 'Report')]);
            expect(element.querySelector(ROW_DELETE)).toBeNull();

            superadmin.set(true);
            fixture.detectChanges();

            expect(element.querySelector(ROW_DELETE)).not.toBeNull();
        });

        it('offers restore but not delete forever with CREATE and DELETE', () => {
            grant(ResourceCode.Flows, ActionCode.Create, ActionCode.Delete);
            const element = openFlowsWith([entry(5, 'Report')]);
            expect(element.querySelector(ROW_RESTORE)).not.toBeNull();
            expect(element.querySelector(ROW_DELETE)).toBeNull();

            checkRow(element, 0);

            expect(element.querySelector(RESTORE_SELECTED)).not.toBeNull();
            expect(element.querySelector(DELETE_SELECTED)).toBeNull();
        });

        it('offers the delete-forever actions to a superadmin', () => {
            superadmin.set(true);
            grant(ResourceCode.Flows);
            const element = openFlowsWith([entry(5, 'Report')]);
            expect(element.querySelector(ROW_DELETE)).not.toBeNull();
            expect(element.querySelector(ROW_RESTORE)).not.toBeNull();

            checkRow(element, 0);

            expect(element.querySelector(DELETE_SELECTED)).not.toBeNull();
            expect(element.querySelector(RESTORE_SELECTED)).not.toBeNull();
        });
    });

    describe('row actions', () => {
        it('restores a row through the bulk endpoint, toasts the new name and reloads', () => {
            grant(ResourceCode.Flows, ActionCode.Create);
            const element = openFlowsWith([entry(5, 'Report')]);

            click(element, ROW_RESTORE);
            const request = httpTesting.expectOne({ method: 'POST', url: `${FLOWS_BIN}restore/` });
            expect(request.request.body).toEqual({ ids: [5] });
            request.flush({
                restored: [{ id: 5, name: 'Report #2', renamed_from: 'Report', links_restored: false }],
                failed: [],
            });

            expect(toast.success).toHaveBeenCalledWith(
                `"Report" restored as "Report #2", because that name was taken. Its links to other items aren't restored.`
            );
            httpTesting.expectOne(FLOWS_LIST).flush(page([]));
        });

        it('refreshes the secret pickers after a secret is restored, so it stops reading as binned', () => {
            grant(ResourceCode.Secrets, ActionCode.Create);
            const secretsBin = `${API_URL}secrets/recycle-bin/`;
            const element = open('secrets');
            httpTesting.expectOne(listUrl(secretsBin)).flush(page([entry(3, 'API key')]));
            fixture.detectChanges();

            click(element, ROW_RESTORE);
            httpTesting.expectOne({ method: 'POST', url: `${secretsBin}restore/` }).flush({
                restored: [{ id: 3, name: 'API key', renamed_from: null, links_restored: true }],
                failed: [],
            });
            expect(toast.success).toHaveBeenCalledWith(
                `"API key" restored. Everything that used it is connected again.`
            );

            // The tab's own reload, and the pickers' cache: the live list and the bin list.
            httpTesting.expectOne(listUrl(secretsBin)).flush(page([]));
            httpTesting.expectOne(`${API_URL}secrets/`).flush({ results: [] });
            httpTesting.expectOne(`${secretsBin}?limit=100&offset=0`).flush(page([]));
        });

        it('restores without asking', () => {
            grant(ResourceCode.Flows, ActionCode.Create);
            const element = openFlowsWith([entry(5, 'Report')]);

            click(element, ROW_RESTORE);

            expect(confirm).not.toHaveBeenCalled();
            httpTesting.expectOne({ method: 'POST', url: `${FLOWS_BIN}restore/` });
        });

        it('asks before a permanent delete, with no phrase to type, and a cancel sends nothing', () => {
            superadmin.set(true);
            grant(ResourceCode.Flows);
            confirm.mockReturnValue(of<ConfirmationResult>('close'));
            const element = openFlowsWith([entry(5, '<img src=x>')]);

            click(element, ROW_DELETE);

            expect(lastConfirm()).toMatchObject({ type: 'danger' });
            expect(lastConfirm().verification).toBeUndefined();
            expect(lastConfirm().message).toContain('&lt;img src=x&gt;');
            httpTesting.expectNone({ method: 'POST' });
        });

        it('purges a row after the confirmation', () => {
            superadmin.set(true);
            grant(ResourceCode.Flows);
            const element = openFlowsWith([entry(5, 'Report')]);

            click(element, ROW_DELETE);
            const request = httpTesting.expectOne({ method: 'POST', url: `${FLOWS_BIN}purge/` });
            expect(request.request.body).toEqual({ ids: [5] });
            request.flush({ purged: [5], failed: [] });

            expect(toast.success).toHaveBeenCalledWith('"Report" deleted permanently.');
            httpTesting.expectOne(FLOWS_LIST).flush(page([]));
        });

        it('explains a 404 and reloads', () => {
            grant(ResourceCode.Flows, ActionCode.Create);
            const element = openFlowsWith([entry(5, 'Report')]);

            click(element, ROW_RESTORE);
            httpTesting
                .expectOne({ method: 'POST', url: `${FLOWS_BIN}restore/` })
                .flush({ message: 'Not found.' }, { status: 404, statusText: 'Not Found' });

            expect(toast.error).toHaveBeenCalledWith('This item is no longer in the recycle bin.');
            httpTesting.expectOne(FLOWS_LIST).flush(page([]));
        });

        it('leaves a 403 to the forbidden interceptor: no toast and no reload', () => {
            grant(ResourceCode.Flows, ActionCode.Create);
            const element = openFlowsWith([entry(5, 'Report')]);

            click(element, ROW_RESTORE);
            httpTesting
                .expectOne({ method: 'POST', url: `${FLOWS_BIN}restore/` })
                .flush({ message: 'Forbidden' }, { status: 403, statusText: 'Forbidden' });

            expect(toast.error).not.toHaveBeenCalled();
            httpTesting.expectNone(FLOWS_LIST);
        });

        it('leaves a 403 on delete forever (stale superadmin state) to the forbidden interceptor', () => {
            superadmin.set(true);
            grant(ResourceCode.Flows);
            const element = openFlowsWith([entry(5, 'Report')]);

            click(element, ROW_DELETE);
            httpTesting
                .expectOne({ method: 'POST', url: `${FLOWS_BIN}purge/` })
                .flush(
                    { message: 'Superadmin privileges are required for this action.' },
                    { status: 403, statusText: 'Forbidden' }
                );

            expect(toast.error).not.toHaveBeenCalled();
            httpTesting.expectNone(FLOWS_LIST);
        });

        it('shows the reason of an item the backend skipped (a storage restore conflict)', () => {
            grant(ResourceCode.Files, ActionCode.Create);
            const element = open('files');
            httpTesting.expectOne(FILES_LIST).flush(page([storageEntry(12, 'docs/a.txt')]));
            fixture.detectChanges();

            click(element, ROW_RESTORE);
            const message = "Can't restore to 'docs/a.txt': storage already holds a file there.";
            const request = httpTesting.expectOne({ method: 'POST', url: `${API_URL}storage/recycle-bin/restore/` });
            expect(request.request.body).toEqual({ ids: [12] });
            request.flush({ restored: [], failed: [{ id: 12, name: 'docs/a.txt', message }] });

            expect(toast.success).not.toHaveBeenCalled();
            expect(toast.error).toHaveBeenCalledWith(`Couldn't restore 1 item. "docs/a.txt": ${message}`);
            httpTesting.expectOne(FILES_LIST).flush(page([]));
        });

        it('names a storage row by its full path in the delete dialog', () => {
            superadmin.set(true);
            grant(ResourceCode.Files);
            confirm.mockReturnValue(of<ConfirmationResult>('close'));
            const element = open('files');
            httpTesting.expectOne(FILES_LIST).flush(page([storageEntry(12, 'docs/reports/a.txt')]));
            fixture.detectChanges();

            click(element, ROW_DELETE);

            expect(lastConfirm().message).toContain('docs/reports/a.txt');
        });
    });

    describe('selection and toolbar', () => {
        beforeEach(() => {
            superadmin.set(true);
            grant(ResourceCode.Flows);
        });

        it('shows the bulk buttons only while rows are selected, as outlined text buttons', () => {
            const element = openFlowsWith([entry(5, 'Report'), entry(6, 'Digest'), entry(7, 'Sync')]);
            expect(element.querySelector('.bin-toolbar__actions')).toBeNull();

            checkRow(element, 0);

            const restore = element.querySelector<HTMLButtonElement>(RESTORE_SELECTED);
            const remove = element.querySelector<HTMLButtonElement>(DELETE_SELECTED);
            expect(restore?.textContent?.trim()).toBe('Restore (1)');
            expect(restore?.classList).toContain('btn-outline-primary');
            expect(remove?.textContent?.trim()).toBe('Delete (1)');
            expect(remove?.classList).toContain('btn-outline-danger');
        });

        it('selects every row with the header checkbox, and clears them again', () => {
            const element = openFlowsWith([entry(5, 'Report'), entry(6, 'Digest'), entry(7, 'Sync')]);
            const header = (): HTMLInputElement =>
                element.querySelector<HTMLInputElement>('.table-header app-checkbox input')!;

            header().click();
            fixture.detectChanges();
            expect(element.querySelector(RESTORE_SELECTED)?.textContent?.trim()).toBe('Restore (3)');

            header().click();
            fixture.detectChanges();
            expect(element.querySelector('.bin-toolbar__actions')).toBeNull();
        });

        it('clears a partial selection with the header checkbox', () => {
            const element = openFlowsWith([entry(5, 'Report'), entry(6, 'Digest'), entry(7, 'Sync')]);
            checkRow(element, 0);

            element.querySelector<HTMLInputElement>('.table-header app-checkbox input')!.click();
            fixture.detectChanges();

            expect(element.querySelector('.bin-toolbar__actions')).toBeNull();
        });

        it('restores the selected rows by id, lists the renames and clears the selection', () => {
            const element = openFlowsWith([
                entry(5, 'Report', { deleted_at: '2026-10-03T10:00:00Z' }),
                entry(6, 'Digest', { deleted_at: '2026-10-02T10:00:00Z' }),
                entry(7, 'Sync'),
            ]);
            checkRow(element, 0);
            checkRow(element, 1);

            click(element, RESTORE_SELECTED);
            expect(confirm).not.toHaveBeenCalled();
            const request = httpTesting.expectOne({ method: 'POST', url: `${FLOWS_BIN}restore/` });
            expect(request.request.body).toEqual({ ids: [5, 6] });
            request.flush({
                restored: [
                    { id: 5, name: 'Report #2', renamed_from: 'Report', links_restored: false },
                    { id: 6, name: 'Digest', renamed_from: null, links_restored: false },
                ],
                failed: [],
            });

            expect(toast.success).toHaveBeenCalledWith(
                `2 restored, 1 renamed: Report → Report #2. Their links to other items aren't restored.`
            );
            httpTesting.expectOne(FLOWS_LIST).flush(page([entry(7, 'Sync')]));
            fixture.detectChanges();
            expect(element.querySelector('.bin-toolbar__actions')).toBeNull();
        });

        it('confirms deleting the selected rows without a typed phrase, and lists what failed', () => {
            const element = openFlowsWith([
                entry(5, 'Report', { deleted_at: '2026-10-03T10:00:00Z' }),
                entry(6, 'Digest', { deleted_at: '2026-10-02T10:00:00Z' }),
            ]);
            checkRow(element, 0);
            checkRow(element, 1);

            click(element, DELETE_SELECTED);
            expect(lastConfirm()).toMatchObject({ type: 'danger' });
            expect(lastConfirm().verification).toBeUndefined();
            const request = httpTesting.expectOne({ method: 'POST', url: `${FLOWS_BIN}purge/` });
            expect(request.request.body).toEqual({ ids: [5, 6] });
            request.flush({ purged: [5], failed: [{ id: 6, name: 'Digest', message: 'It is locked.' }] });

            expect(toast.success).toHaveBeenCalledWith('1 item deleted permanently.');
            expect(toast.error).toHaveBeenCalledWith(`Couldn't delete 1 item. "Digest": It is locked.`);
            httpTesting.expectOne(FLOWS_LIST).flush(page([]));
        });

        it('sends nothing when a bulk delete is cancelled', () => {
            confirm.mockReturnValue(of<ConfirmationResult>(false));
            const element = openFlowsWith([entry(5, 'Report')]);
            checkRow(element, 0);

            click(element, DELETE_SELECTED);

            httpTesting.expectNone({ method: 'POST' });
        });
    });

    describe('kind filter', () => {
        function chooseKind(value: string | null): void {
            const table = fixture.debugElement.query(By.directive(RecycleBinTableComponent));
            (table.componentInstance as RecycleBinTableComponent).kindFilterChanged.emit(value);
            fixture.detectChanges();
        }

        it('switches the Tools tab between its two bins, Python tools first, with no "All"', () => {
            const pythonBin = `${API_URL}python-code-tool/recycle-bin/`;
            const mcpBin = `${API_URL}mcp-tools/recycle-bin/`;
            grant(ResourceCode.Tools, ActionCode.Create);
            const element = open('tools');
            httpTesting.expectOne(listUrl(pythonBin)).flush(page([entry(1, 'Parser')]));
            fixture.detectChanges();
            const trigger = element.querySelector('.col-label--filter');
            expect(trigger?.textContent?.trim()).toBe('Python tools');
            // Always one bin chosen: no narrowing filter to mark.
            expect(trigger?.textContent).not.toContain('(1)');
            const select = fixture.debugElement.query(By.directive(SelectComponent));
            expect(select.componentInstance.items().map((item: { name: string }) => item.name)).toEqual([
                'Python tools',
                'MCP tools',
            ]);
            checkRow(element, 0);

            chooseKind('mcp_tool');

            expect(element.querySelector('.bin-toolbar__actions')).toBeNull();
            httpTesting.expectOne(listUrl(mcpBin)).flush(page([entry(1, 'Search')]));
            fixture.detectChanges();
            expect(rowNames(element)).toEqual(['Search']);
            expect(element.querySelector('.col-label--filter')?.textContent?.trim()).toBe('MCP tools');
        });

        it('acts on the bin shown: a bulk restore on MCP tools goes to the MCP bin', () => {
            const mcpBin = `${API_URL}mcp-tools/recycle-bin/`;
            grant(ResourceCode.Tools, ActionCode.Create);
            const element = open('tools');
            httpTesting.expectOne(listUrl(`${API_URL}python-code-tool/recycle-bin/`)).flush(page([]));
            fixture.detectChanges();
            chooseKind('mcp_tool');
            httpTesting.expectOne(listUrl(mcpBin)).flush(page([entry(4, 'Search'), entry(5, 'Fetch')]));
            fixture.detectChanges();

            element.querySelector<HTMLInputElement>('.table-header app-checkbox input')!.click();
            fixture.detectChanges();
            click(element, RESTORE_SELECTED);

            const request = httpTesting.expectOne({ method: 'POST', url: `${mcpBin}restore/` });
            expect(request.request.body).toEqual({ ids: [4, 5] });
            request.flush({ restored: [], failed: [] });
            httpTesting.expectOne(listUrl(mcpBin)).flush(page([]));
        });

        it('keeps the switch when the bin shown is empty, so the other one stays reachable', () => {
            grant(ResourceCode.Tools);
            const element = open('tools');
            httpTesting.expectOne(listUrl(`${API_URL}python-code-tool/recycle-bin/`)).flush(page([]));
            fixture.detectChanges();

            expect(element.textContent).not.toContain('The recycle bin is empty');
            expect(element.querySelector('.col-label--filter')?.textContent).toContain('Python tools');
            expect(element.querySelector('.bin-no-results')?.textContent?.trim()).toBe('No deleted Python tools.');
        });

        it('asks the server for one item type on the Files tab, from the first page', () => {
            grant(ResourceCode.Files);
            open('files');
            httpTesting.expectOne(FILES_LIST).flush(page([storageEntry(1, 'docs/report.pdf')]));
            fixture.detectChanges();

            chooseKind('folder');

            httpTesting
                .expectOne(listUrl(`${API_URL}storage/recycle-bin/`, '&item_type=folder'))
                .flush(page([storageEntry(2, 'docs/old/')]));
        });

        it('has no kind filter on a tab without a Kind column', () => {
            grant(ResourceCode.Surfaces);
            const element = open('surfaces');
            httpTesting.expectOne(listUrl(`${API_URL}surfaces/recycle-bin/`)).flush(page([entry(8, 'Support chat')]));
            fixture.detectChanges();
            expect(element.querySelector('.col-label--filter')).toBeNull();
        });
    });

    describe('count column', () => {
        function countHeader(element: HTMLElement): string | undefined {
            return element.querySelector('.col-label--filter')?.textContent?.trim();
        }

        function chooseCount(value: string | null): void {
            const table = fixture.debugElement.query(By.directive(RecycleBinTableComponent));
            (table.componentInstance as RecycleBinTableComponent).countFilterChanged.emit(value);
            fixture.detectChanges();
        }

        it('shows the node count of each flow, asks the server for has / has none, and clears the selection', () => {
            grant(ResourceCode.Flows, ActionCode.Create);
            const element = openFlowsWith([
                { ...entry(5, 'Report'), contents_total: 2 },
                { ...entry(6, 'Digest'), contents_total: 9 },
                { ...entry(7, 'Daily report'), contents_total: 0 },
            ]);
            expect(countHeader(element)).toBe('Nodes');
            expect(Array.from(element.querySelectorAll('.bin-count'), (cell) => cell.textContent?.trim())).toEqual([
                '2',
                '9',
                '0',
            ]);
            checkRow(element, 0);

            chooseCount('some');
            expect(element.querySelector('.bin-toolbar__actions')).toBeNull();
            httpTesting
                .expectOne(listUrl(FLOWS_BIN, '&contents=some'))
                .flush(page([{ ...entry(5, 'Report'), contents_total: 2 }]));
            fixture.detectChanges();
            expect(rowNames(element)).toEqual(['Report']);

            chooseCount('none');
            httpTesting.expectOne(listUrl(FLOWS_BIN, '&contents=none')).flush(page([]));

            chooseCount(null);
            httpTesting.expectOne(FLOWS_LIST).flush(page([]));
        });

        it('labels the count "Surfaces" on the Agents tab', () => {
            grant(ResourceCode.Agents);
            const element = open('agents');
            httpTesting
                .expectOne(listUrl(`${API_URL}agent-definitions/recycle-bin/`))
                .flush(page([entry(4, 'Writer')]));
            fixture.detectChanges();
            expect(countHeader(element)).toBe('Surfaces');
        });

        it('has no count column on other tabs', () => {
            grant(ResourceCode.Surfaces);
            const element = open('surfaces');
            httpTesting.expectOne(listUrl(`${API_URL}surfaces/recycle-bin/`)).flush(page([entry(8, 'Support chat')]));
            fixture.detectChanges();
            expect(element.querySelector('.bin-count')).toBeNull();
        });
    });

    describe('search and sort', () => {
        it('flips only the clicked arrow, on its first click, and sorts by it', () => {
            grant(ResourceCode.Flows);
            const element = openFlowsWith([
                entry(5, 'Newer', { deleted_at: '2026-10-03T10:00:00Z' }),
                entry(6, 'Older', { deleted_at: '2026-10-01T10:00:00Z' }),
            ]);
            const headers = (): NodeListOf<HTMLButtonElement> =>
                element.querySelectorAll<HTMLButtonElement>('.table-header .sort-header');
            const arrowUp = (index: number): boolean =>
                headers()[index].querySelector('.sort-header__icon--asc') !== null;
            expect([arrowUp(0), arrowUp(1)]).toEqual([false, false]);

            headers()[1].click();
            fixture.detectChanges();
            expect([arrowUp(0), arrowUp(1)]).toEqual([false, true]);
            httpTesting
                .expectOne(`${FLOWS_BIN}?limit=50&offset=0&ordering=days_left`)
                .flush(page([entry(6, 'Older'), entry(5, 'Newer')]));
            fixture.detectChanges();
            expect(rowNames(element)).toEqual(['Older', 'Newer']);

            headers()[0].click();
            fixture.detectChanges();
            expect([arrowUp(0), arrowUp(1)]).toEqual([true, true]);
            httpTesting.expectOne(`${FLOWS_BIN}?limit=50&offset=0&ordering=deleted_at`).flush(page([]));
        });

        it('loads every content of a capped row with "Show all"', () => {
            grant(ResourceCode.Flows);
            const element = openFlowsWith([
                { ...entry(5, 'Report'), contents_total: 3, contents: [{ name: 'Start', kind: 'start' }] },
            ]);
            click(element, 'button.bin-name');

            const showAll = element.querySelector<HTMLButtonElement>('.flow-node-list__more--action');
            expect(showAll?.textContent?.trim()).toBe('Show all 3');
            showAll!.click();
            httpTesting.expectOne(`${API_URL}graphs/5/recycle-bin-contents/`).flush({
                contents: [
                    { name: 'Start', kind: 'start' },
                    { name: 'Write', kind: 'task' },
                    { name: 'Send', kind: 'task' },
                ],
                contents_total: 3,
            });
            fixture.detectChanges();

            expect(element.querySelectorAll('.flow-node-list__row').length).toBe(3);
            expect(element.querySelector('.flow-node-list__more')).toBeNull();
        });

        it('expands every row with "Expand all", then collapses them with "Collapse all"', () => {
            grant(ResourceCode.Flows);
            const element = openFlowsWith([
                { ...entry(5, 'Report'), contents_total: 1, contents: [{ name: 'Start', kind: 'start' }] },
                { ...entry(6, 'Digest'), contents_total: 1, contents: [{ name: 'Start', kind: 'start' }] },
            ]);
            const button = (): HTMLElement => element.querySelector<HTMLElement>('.bin-toolbar__expand-all button')!;
            const expandedRows = (): number => element.querySelectorAll('.bin-expansion.expanded').length;

            expect(button().textContent?.trim()).toBe('Expand all');
            button().click();
            fixture.detectChanges();
            expect(expandedRows()).toBe(2);
            expect(button().textContent?.trim()).toBe('Collapse all');

            button().click();
            fixture.detectChanges();
            expect(expandedRows()).toBe(0);
        });

        it('offers no search while the list loads, or when the bin is empty', () => {
            grant(ResourceCode.Flows);
            const element = open('flows');
            expect(element.querySelector('app-search')).toBeNull();

            httpTesting.expectOne(FLOWS_LIST).flush(page([]));
            fixture.detectChanges();
            expect(element.querySelector('app-search')).toBeNull();
        });

        it('keeps the search when a search is what emptied the list, so it can be undone', () => {
            vi.useFakeTimers();
            grant(ResourceCode.Flows);
            const element = openFlowsWith([entry(5, 'Report')]);

            search('nothing');
            vi.advanceTimersByTime(300);
            httpTesting.expectOne(listUrl(FLOWS_BIN, '&search=nothing')).flush(page([]));
            fixture.detectChanges();

            expect(rowNames(element)).toEqual([]);
            expect(element.querySelector('app-search')).not.toBeNull();
        });

        it('asks the server to search and sort every list, from the first page', () => {
            vi.useFakeTimers();
            grant(ResourceCode.Flows);
            const element = openFlowsWith([entry(5, 'Report'), entry(6, 'Digest')]);

            search('rep');
            // Typing waits for a pause before it asks.
            httpTesting.expectNone(() => true);
            vi.advanceTimersByTime(300);
            httpTesting.expectOne(listUrl(FLOWS_BIN, '&search=rep')).flush(page([entry(5, 'Report')]));
            fixture.detectChanges();
            expect(rowNames(element)).toEqual(['Report']);

            click(element, '.table-header .sort-header');
            httpTesting.expectOne(`${FLOWS_BIN}?limit=50&offset=0&ordering=deleted_at&search=rep`).flush(page([]));
            fixture.detectChanges();
            expect(element.textContent).toContain('No items match the current search or filters.');
        });

        it('asks the server to search and sort the paged Files list, from the first page', () => {
            vi.useFakeTimers();
            grant(ResourceCode.Files);
            const element = open('files');
            httpTesting.expectOne(FILES_LIST).flush(page([storageEntry(1, 'docs/report.pdf')]));
            fixture.detectChanges();

            search('rep');
            vi.advanceTimersByTime(300);
            httpTesting
                .expectOne(listUrl(`${API_URL}storage/recycle-bin/`, '&search=rep'))
                .flush(page([storageEntry(1, 'docs/report.pdf')]));
            fixture.detectChanges();

            // Deleted at, newest first by default: a click flips it to oldest first.
            click(element, '.table-header .sort-header');
            httpTesting
                .expectOne(`${API_URL}storage/recycle-bin/?limit=50&offset=0&ordering=deleted_at&search=rep`)
                .flush(page([storageEntry(1, 'docs/report.pdf')]));
        });
    });

    describe('paging', () => {
        function flows(count: number, firstId: number): ReturnType<typeof entry>[] {
            return Array.from({ length: count }, (_, index) => entry(firstId + index, `Flow ${firstId + index}`));
        }

        function requestPage(pageNumber: number): void {
            const table = fixture.debugElement.query(By.directive(RecycleBinTableComponent));
            (table.componentInstance as RecycleBinTableComponent).pageRequested.emit(pageNumber);
        }

        it('pages every tab, selects only the page shown, and reloads the same page after an action', () => {
            grant(ResourceCode.Flows, ActionCode.Create);
            const element = open('flows');
            httpTesting.expectOne(FLOWS_LIST).flush(page(flows(50, 1), 120));
            fixture.detectChanges();
            expect(element.querySelector('app-pagination-controls')).not.toBeNull();

            requestPage(2);
            const secondPage = `${FLOWS_BIN}?limit=50&offset=50&ordering=-deleted_at`;
            httpTesting.expectOne(secondPage).flush(page(flows(50, 51), 120));
            fixture.detectChanges();

            element.querySelector<HTMLInputElement>('.table-header app-checkbox input')!.click();
            fixture.detectChanges();
            expect(element.querySelector(RESTORE_SELECTED)?.textContent?.trim()).toBe('Restore (50)');

            click(element, RESTORE_SELECTED);
            const request = httpTesting.expectOne({ method: 'POST', url: `${FLOWS_BIN}restore/` });
            expect(request.request.body.ids[0]).toBe(51);
            request.flush({ restored: [], failed: [] });
            httpTesting.expectOne(secondPage).flush(page(flows(20, 101), 70));
        });

        it('keeps the page when the count filter is set to the value it already has', () => {
            grant(ResourceCode.Flows);
            open('flows');
            httpTesting.expectOne(FLOWS_LIST).flush(page(flows(50, 1), 120));
            fixture.detectChanges();
            requestPage(2);
            httpTesting
                .expectOne(`${FLOWS_BIN}?limit=50&offset=50&ordering=-deleted_at`)
                .flush(page(flows(50, 51), 120));

            const table = fixture.debugElement.query(By.directive(RecycleBinTableComponent));
            (table.componentInstance as RecycleBinTableComponent).countFilterChanged.emit(null);

            httpTesting.expectNone(() => true);
        });

        it('lets a newer load replace one still in flight, so a late answer cannot overwrite it', () => {
            grant(ResourceCode.Flows);
            const element = open('flows');
            httpTesting.expectOne(FLOWS_LIST).flush(page(flows(50, 1), 120));
            fixture.detectChanges();

            requestPage(2);
            const older = httpTesting.expectOne(`${FLOWS_BIN}?limit=50&offset=50&ordering=-deleted_at`);
            requestPage(3);
            const newer = httpTesting.expectOne(`${FLOWS_BIN}?limit=50&offset=100&ordering=-deleted_at`);

            expect(older.cancelled).toBe(true);
            newer.flush(page([entry(101, 'Newest page')], 120));
            fixture.detectChanges();
            // A late answer to the cancelled request has nowhere to go.
            expect(() => older.flush(page(flows(50, 51), 120))).toThrow();
            fixture.detectChanges();
            expect(rowNames(element)).toEqual(['Newest page']);
        });

        it('starts from the first page again when the search changes', () => {
            vi.useFakeTimers();
            grant(ResourceCode.Flows);
            open('flows');
            httpTesting.expectOne(FLOWS_LIST).flush(page(flows(50, 1), 120));
            fixture.detectChanges();
            requestPage(3);
            httpTesting
                .expectOne(`${FLOWS_BIN}?limit=50&offset=100&ordering=-deleted_at`)
                .flush(page(flows(20, 101), 120));
            fixture.detectChanges();

            search('flow');
            vi.advanceTimersByTime(300);
            httpTesting.expectOne(listUrl(FLOWS_BIN, '&search=flow')).flush(page([]));
        });
    });

    it('loads the Key-value tables tab and restores through its own bin', () => {
        grant(ResourceCode.KeyValueTables, ActionCode.Create);
        const element = open('key-value-tables');
        httpTesting.expectOne(listUrl(`${API_URL}key-value-tables/recycle-bin/`)).flush(page([entry(6, 'Prices')]));
        fixture.detectChanges();

        click(element, ROW_RESTORE);
        httpTesting.expectOne({ method: 'POST', url: `${API_URL}key-value-tables/recycle-bin/restore/` }).flush({
            restored: [{ id: 6, name: 'Prices #2', renamed_from: 'Prices', links_restored: false }],
            failed: [],
        });
        httpTesting.expectOne(listUrl(`${API_URL}key-value-tables/recycle-bin/`)).flush(page([]));
    });

    it('expands an agent row to the surfaces its restore brings back', () => {
        grant(ResourceCode.Agents);
        const element = open('agents');
        httpTesting
            .expectOne(listUrl(`${API_URL}agent-definitions/recycle-bin/`))
            .flush(
                page([
                    { ...entry(4, 'Writer'), contents: [{ name: 'Support chat', kind: 'surface' }], contents_total: 1 },
                ])
            );
        fixture.detectChanges();

        click(element, 'button.bin-name');

        const nodeList = element.querySelector('.flow-node-list');
        expect(nodeList?.classList).toContain('expanded');
        expect(nodeList?.textContent).toContain('Support chat');
    });
});
