import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import {
    ConfirmationDialogData,
    ConfirmationDialogService,
    ConfirmationResult,
    SearchComponent,
} from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { Observable, of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { RecycleBinSettingsStorageService } from '../../../../services/recycle-bin';
import { GetRecycleBinDetailResponse, RecycleBinTabKey } from '../../models/recycle-bin.model';
import { RecycleBinTableComponent } from '../recycle-bin-table/recycle-bin-table.component';
import { RecycleBinTabComponent } from './recycle-bin-tab.component';

const API_URL = 'http://api/';
const FLOWS_LIST = `${API_URL}graphs/recycle-bin/`;
const FILES_LIST = `${API_URL}storage/recycle-bin/?limit=50&offset=0&ordering=-deleted_at`;

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

function storagePage(results: ReturnType<typeof storageEntry>[]) {
    return { count: results.length, next: null, previous: null, results };
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
    let toast: { success: ReturnType<typeof vi.fn>; error: ReturnType<typeof vi.fn> };
    let confirm: ReturnType<typeof vi.fn<(options: ConfirmationDialogData) => Observable<ConfirmationResult>>>;

    beforeEach(() => {
        grants = [];
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
                        can: (resource: ResourceCode, action: ActionCode) =>
                            grants.some(
                                ([grantedResource, grantedAction]) =>
                                    grantedResource === resource && grantedAction === action
                            ),
                    },
                },
                { provide: ToastService, useValue: toast },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                { provide: RecycleBinSettingsStorageService, useValue: { retentionDays: signal(7) } },
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
        httpTesting.expectOne(FLOWS_LIST).flush(entries);
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

        it('offers only the delete actions with DELETE', () => {
            grant(ResourceCode.Flows, ActionCode.Delete);
            const element = openFlowsWith([entry(5, 'Report')]);
            expect(element.querySelector(ROW_RESTORE)).toBeNull();

            checkRow(element, 0);

            expect(element.querySelector(DELETE_SELECTED)).not.toBeNull();
            expect(element.querySelector(RESTORE_SELECTED)).toBeNull();
        });
    });

    describe('row actions', () => {
        it('restores a row through the bulk endpoint, toasts the new name and reloads', () => {
            grant(ResourceCode.Flows, ActionCode.Create);
            const element = openFlowsWith([entry(5, 'Report')]);

            click(element, ROW_RESTORE);
            const request = httpTesting.expectOne({ method: 'POST', url: `${FLOWS_LIST}restore/` });
            expect(request.request.body).toEqual({ ids: [5] });
            request.flush({ restored: [{ id: 5, name: 'Report #2', renamed_from: 'Report' }], failed: [] });

            expect(toast.success).toHaveBeenCalledWith(
                `"Report" restored as "Report #2", because that name was taken. Its links to other items aren't restored.`
            );
            httpTesting.expectOne(FLOWS_LIST).flush([]);
        });

        it('restores without asking', () => {
            grant(ResourceCode.Flows, ActionCode.Create);
            const element = openFlowsWith([entry(5, 'Report')]);

            click(element, ROW_RESTORE);

            expect(confirm).not.toHaveBeenCalled();
            httpTesting.expectOne({ method: 'POST', url: `${FLOWS_LIST}restore/` });
        });

        it('asks before a permanent delete, with no phrase to type, and a cancel sends nothing', () => {
            grant(ResourceCode.Flows, ActionCode.Delete);
            confirm.mockReturnValue(of<ConfirmationResult>('close'));
            const element = openFlowsWith([entry(5, '<img src=x>')]);

            click(element, ROW_DELETE);

            expect(lastConfirm()).toMatchObject({ type: 'danger' });
            expect(lastConfirm().verification).toBeUndefined();
            expect(lastConfirm().message).toContain('&lt;img src=x&gt;');
            httpTesting.expectNone({ method: 'POST' });
        });

        it('purges a row after the confirmation', () => {
            grant(ResourceCode.Flows, ActionCode.Delete);
            const element = openFlowsWith([entry(5, 'Report')]);

            click(element, ROW_DELETE);
            const request = httpTesting.expectOne({ method: 'POST', url: `${FLOWS_LIST}purge/` });
            expect(request.request.body).toEqual({ ids: [5] });
            request.flush({ purged: [5], failed: [] });

            expect(toast.success).toHaveBeenCalledWith('"Report" deleted permanently.');
            httpTesting.expectOne(FLOWS_LIST).flush([]);
        });

        it('explains a 404 and reloads', () => {
            grant(ResourceCode.Flows, ActionCode.Create);
            const element = openFlowsWith([entry(5, 'Report')]);

            click(element, ROW_RESTORE);
            httpTesting
                .expectOne({ method: 'POST', url: `${FLOWS_LIST}restore/` })
                .flush({ message: 'Not found.' }, { status: 404, statusText: 'Not Found' });

            expect(toast.error).toHaveBeenCalledWith('This item is no longer in the recycle bin.');
            httpTesting.expectOne(FLOWS_LIST).flush([]);
        });

        it('leaves a 403 to the forbidden interceptor: no toast and no reload', () => {
            grant(ResourceCode.Flows, ActionCode.Create);
            const element = openFlowsWith([entry(5, 'Report')]);

            click(element, ROW_RESTORE);
            httpTesting
                .expectOne({ method: 'POST', url: `${FLOWS_LIST}restore/` })
                .flush({ message: 'Forbidden' }, { status: 403, statusText: 'Forbidden' });

            expect(toast.error).not.toHaveBeenCalled();
            httpTesting.expectNone(FLOWS_LIST);
        });

        it('shows the reason of an item the backend skipped (a storage restore conflict)', () => {
            grant(ResourceCode.Files, ActionCode.Create);
            const element = open('files');
            httpTesting.expectOne(FILES_LIST).flush(storagePage([storageEntry(12, 'docs/a.txt')]));
            fixture.detectChanges();

            click(element, ROW_RESTORE);
            const message = "Can't restore to 'docs/a.txt': storage already holds a file there.";
            const request = httpTesting.expectOne({ method: 'POST', url: `${API_URL}storage/recycle-bin/restore/` });
            expect(request.request.body).toEqual({ ids: [12] });
            request.flush({ restored: [], failed: [{ id: 12, name: 'docs/a.txt', message }] });

            expect(toast.success).not.toHaveBeenCalled();
            expect(toast.error).toHaveBeenCalledWith(`Couldn't restore 1 item. "docs/a.txt": ${message}`);
            httpTesting.expectOne(FILES_LIST).flush(storagePage([]));
        });

        it('names a storage row by its full path in the delete dialog', () => {
            grant(ResourceCode.Files, ActionCode.Delete);
            confirm.mockReturnValue(of<ConfirmationResult>('close'));
            const element = open('files');
            httpTesting.expectOne(FILES_LIST).flush(storagePage([storageEntry(12, 'docs/reports/a.txt')]));
            fixture.detectChanges();

            click(element, ROW_DELETE);

            expect(lastConfirm().message).toContain('docs/reports/a.txt');
        });
    });

    describe('selection and toolbar', () => {
        beforeEach(() => grant(ResourceCode.Flows, ActionCode.Create, ActionCode.Delete));

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
            const request = httpTesting.expectOne({ method: 'POST', url: `${FLOWS_LIST}restore/` });
            expect(request.request.body).toEqual({ ids: [5, 6] });
            request.flush({
                restored: [
                    { id: 5, name: 'Report #2', renamed_from: 'Report' },
                    { id: 6, name: 'Digest', renamed_from: null },
                ],
                failed: [],
            });

            expect(toast.success).toHaveBeenCalledWith(
                `2 restored, 1 renamed: Report → Report #2. Their links to other items aren't restored.`
            );
            httpTesting.expectOne(FLOWS_LIST).flush([entry(7, 'Sync')]);
            fixture.detectChanges();
            expect(element.querySelector('.bin-toolbar__actions')).toBeNull();
        });

        it('asks for "delete-<N>-items" before deleting the selected rows, and lists what failed', () => {
            const element = openFlowsWith([
                entry(5, 'Report', { deleted_at: '2026-10-03T10:00:00Z' }),
                entry(6, 'Digest', { deleted_at: '2026-10-02T10:00:00Z' }),
            ]);
            checkRow(element, 0);
            checkRow(element, 1);

            click(element, DELETE_SELECTED);
            expect(lastConfirm()).toMatchObject({ type: 'danger' });
            expect(lastConfirm().verification).toBeUndefined();
            const request = httpTesting.expectOne({ method: 'POST', url: `${FLOWS_LIST}purge/` });
            expect(request.request.body).toEqual({ ids: [5, 6] });
            request.flush({ purged: [5], failed: [{ id: 6, name: 'Digest', message: 'It is locked.' }] });

            expect(toast.success).toHaveBeenCalledWith('1 item deleted permanently.');
            expect(toast.error).toHaveBeenCalledWith(`Couldn't delete 1 item. "Digest": It is locked.`);
            httpTesting.expectOne(FLOWS_LIST).flush([]);
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

        it('filters the Tools tab by tool kind on the client, and clears the selection', () => {
            grant(ResourceCode.Tools, ActionCode.Delete);
            const element = open('tools');
            httpTesting.expectOne(`${API_URL}python-code-tool/recycle-bin/`).flush([entry(1, 'Parser')]);
            httpTesting
                .expectOne(`${API_URL}mcp-tools/recycle-bin/`)
                .flush([entry(1, 'Search', { deleted_at: '2026-10-02T10:00:00Z' })]);
            fixture.detectChanges();
            expect(element.querySelector('.col-label--filter')?.textContent).toContain('Kind');
            checkRow(element, 0);

            chooseKind('mcp_tool');

            expect(rowNames(element)).toEqual(['Search']);
            expect(element.querySelector('.bin-toolbar__actions')).toBeNull();
            httpTesting.expectNone(() => true);
        });

        it('asks the server for one item type on the Files tab, from the first page', () => {
            grant(ResourceCode.Files);
            open('files');
            httpTesting.expectOne(FILES_LIST).flush(storagePage([storageEntry(1, 'docs/report.pdf')]));
            fixture.detectChanges();

            chooseKind('folder');

            httpTesting
                .expectOne(`${API_URL}storage/recycle-bin/?limit=50&offset=0&ordering=-deleted_at&item_type=folder`)
                .flush(storagePage([storageEntry(2, 'docs/old/')]));
        });

        it('has no kind filter on a tab without a Kind column', () => {
            grant(ResourceCode.Surfaces);
            const element = open('surfaces');
            httpTesting.expectOne(`${API_URL}surfaces/recycle-bin/`).flush([entry(8, 'Support chat')]);
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

        it('shows the node count of each flow, filters by has / has none with the search, and clears the selection', () => {
            grant(ResourceCode.Flows, ActionCode.Delete);
            const element = openFlowsWith([
                { ...entry(5, 'Report', { deleted_at: '2026-10-03T10:00:00Z' }), contents_total: 2 },
                { ...entry(6, 'Digest', { deleted_at: '2026-10-02T10:00:00Z' }), contents_total: 9 },
                { ...entry(7, 'Daily report', { deleted_at: '2026-10-01T10:00:00Z' }), contents_total: 0 },
            ]);
            expect(countHeader(element)).toBe('Nodes');
            expect(Array.from(element.querySelectorAll('.bin-count'), (cell) => cell.textContent?.trim())).toEqual([
                '2',
                '9',
                '0',
            ]);
            checkRow(element, 0);

            chooseCount('some');
            expect(rowNames(element)).toEqual(['Report', 'Digest']);
            expect(element.querySelector('.bin-toolbar__actions')).toBeNull();

            chooseCount('none');
            expect(rowNames(element)).toEqual(['Daily report']);

            chooseCount(null);
            search('report');
            chooseCount('some');
            expect(rowNames(element)).toEqual(['Report']);
            httpTesting.expectNone(() => true);
        });

        it('labels the count "Surfaces" on the Agents tab', () => {
            grant(ResourceCode.Agents);
            const element = open('agents');
            httpTesting.expectOne(`${API_URL}agent-definitions/recycle-bin/`).flush([entry(4, 'Writer')]);
            fixture.detectChanges();
            expect(countHeader(element)).toBe('Surfaces');
        });

        it('has no count column on other tabs', () => {
            grant(ResourceCode.Surfaces);
            const element = open('surfaces');
            httpTesting.expectOne(`${API_URL}surfaces/recycle-bin/`).flush([entry(8, 'Support chat')]);
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
            expect(rowNames(element)).toEqual(['Older', 'Newer']);

            headers()[0].click();
            fixture.detectChanges();
            expect([arrowUp(0), arrowUp(1)]).toEqual([true, true]);
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
            httpTesting.expectOne(`${FLOWS_LIST.replace('recycle-bin/', '')}5/recycle-bin-contents/`).flush({
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

            httpTesting.expectOne(FLOWS_LIST).flush([]);
            fixture.detectChanges();
            expect(element.querySelector('app-search')).toBeNull();
        });

        it('keeps the search when a search is what emptied the list, so it can be undone', () => {
            grant(ResourceCode.Flows);
            const element = openFlowsWith([entry(5, 'Report')]);

            search('nothing like it');

            expect(rowNames(element)).toEqual([]);
            expect(element.querySelector('app-search')).not.toBeNull();
        });

        it('filters and sorts a plain list on the client, with no request', () => {
            grant(ResourceCode.Flows);
            const element = openFlowsWith([
                entry(5, 'Report', { deleted_at: '2026-10-03T10:00:00Z', days_left: 7 }),
                entry(6, 'Digest', { deleted_at: '2026-10-01T10:00:00Z', days_left: 5 }),
                entry(7, 'Daily report', { deleted_at: '2026-10-02T10:00:00Z', days_left: 6 }),
            ]);
            expect(rowNames(element)).toEqual(['Report', 'Daily report', 'Digest']);

            search('rep');
            expect(rowNames(element)).toEqual(['Report', 'Daily report']);

            click(element, '.table-header .sort-header');
            expect(rowNames(element)).toEqual(['Daily report', 'Report']);

            search('nothing like it');
            expect(element.textContent).toContain('No items match the current search or filters.');
            httpTesting.expectNone(() => true);
        });

        it('asks the server to search and sort the paged Files list, from the first page', () => {
            vi.useFakeTimers();
            grant(ResourceCode.Files);
            const element = open('files');
            httpTesting.expectOne(FILES_LIST).flush(storagePage([storageEntry(1, 'docs/report.pdf')]));
            fixture.detectChanges();

            search('rep');
            vi.advanceTimersByTime(300);
            httpTesting
                .expectOne(`${API_URL}storage/recycle-bin/?limit=50&offset=0&ordering=-deleted_at&search=rep`)
                .flush(storagePage([storageEntry(1, 'docs/report.pdf')]));
            fixture.detectChanges();

            // Deleted at, newest first by default: a click flips it to oldest first.
            click(element, '.table-header .sort-header');
            httpTesting
                .expectOne(`${API_URL}storage/recycle-bin/?limit=50&offset=0&ordering=deleted_at&search=rep`)
                .flush(storagePage([storageEntry(1, 'docs/report.pdf')]));
        });
    });

    it('loads the Key-value tables tab and restores through its own bin', () => {
        grant(ResourceCode.KeyValueTables, ActionCode.Create);
        const element = open('key-value-tables');
        httpTesting.expectOne(`${API_URL}key-value-tables/recycle-bin/`).flush([entry(6, 'Prices')]);
        fixture.detectChanges();

        click(element, ROW_RESTORE);
        httpTesting
            .expectOne({ method: 'POST', url: `${API_URL}key-value-tables/recycle-bin/restore/` })
            .flush({ restored: [{ id: 6, name: 'Prices #2', renamed_from: 'Prices' }], failed: [] });
        httpTesting.expectOne(`${API_URL}key-value-tables/recycle-bin/`).flush([]);
    });

    it('expands an agent row to the surfaces its restore brings back', () => {
        grant(ResourceCode.Agents);
        const element = open('agents');
        httpTesting
            .expectOne(`${API_URL}agent-definitions/recycle-bin/`)
            .flush([
                { ...entry(4, 'Writer'), contents: [{ name: 'Support chat', kind: 'surface' }], contents_total: 1 },
            ]);
        fixture.detectChanges();

        click(element, 'button.bin-name');

        const nodeList = element.querySelector('.flow-node-list');
        expect(nodeList?.classList).toContain('expanded');
        expect(nodeList?.textContent).toContain('Support chat');
    });
});
