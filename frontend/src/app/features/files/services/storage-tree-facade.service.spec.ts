import { Dialog } from '@angular/cdk/dialog';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { EMPTY, Observable, of, Subject, throwError } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { RecycleBinSettingsService } from '../../../services/recycle-bin';
import { StorageItem } from '../models/storage.models';
import { StorageApiService } from './storage-api.service';
import { StorageTreeFacade } from './storage-tree-facade.service';

function file(path: string): StorageItem {
    return { name: path.split('/').pop() ?? path, path, type: 'file' };
}

describe('StorageTreeFacade moves', () => {
    let facade: StorageTreeFacade;
    let pendingMoves: Map<string, Subject<void>>;
    let storageApi: {
        refreshTick: ReturnType<typeof signal<number>>;
        triggerRefresh: ReturnType<typeof vi.fn>;
        list: ReturnType<typeof vi.fn>;
        mkdir: ReturnType<typeof vi.fn>;
        move: ReturnType<typeof vi.fn>;
        delete: ReturnType<typeof vi.fn>;
    };
    let toast: {
        success: ReturnType<typeof vi.fn>;
        error: ReturnType<typeof vi.fn>;
        warning: ReturnType<typeof vi.fn>;
        info: ReturnType<typeof vi.fn>;
    };

    beforeEach(() => {
        pendingMoves = new Map();
        storageApi = {
            refreshTick: signal(0),
            triggerRefresh: vi.fn(),
            list: vi.fn(() => of([])),
            mkdir: vi.fn(() => of(undefined)),
            delete: vi.fn(() => of(undefined)),
            move: vi.fn((from: string): Observable<void> => {
                const request = new Subject<void>();
                pendingMoves.set(from, request);
                return request;
            }),
        };
        toast = { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() };

        TestBed.configureTestingModule({
            providers: [
                StorageTreeFacade,
                { provide: StorageApiService, useValue: storageApi },
                { provide: ToastService, useValue: toast },
                { provide: ConfirmationDialogService, useValue: {} },
                { provide: Dialog, useValue: {} },
            ],
        });
        facade = TestBed.inject(StorageTreeFacade);
    });

    function succeed(path: string): void {
        const request = pendingMoves.get(path)!;
        request.next();
        request.complete();
    }

    function fail(path: string): void {
        pendingMoves.get(path)!.error(new Error('move failed'));
    }

    function moveCalls(): string[] {
        return storageApi.move.mock.calls.map(([from]) => from as string);
    }

    it('sends one move at a time, in order', () => {
        const items = [file('a.txt'), file('b.txt'), file('c.txt')];
        facade.onContextAction({ action: 'move', item: items[0], selectedItems: items, targetPath: 'dest' });

        expect(moveCalls()).toEqual(['a.txt']);
        succeed('a.txt');
        expect(moveCalls()).toEqual(['a.txt', 'b.txt']);
        succeed('b.txt');
        expect(moveCalls()).toEqual(['a.txt', 'b.txt', 'c.txt']);
        succeed('c.txt');

        expect(storageApi.move).toHaveBeenCalledWith('a.txt', 'dest');
        expect(toast.success).toHaveBeenCalledWith('3 items moved');
        expect(storageApi.list).toHaveBeenCalledWith('');
    });

    it('keeps going after a failed item, reports the partial failure and reloads the tree', () => {
        const items = [file('a.txt'), file('b.txt'), file('c.txt')];
        facade.onContextAction({ action: 'move', item: items[0], selectedItems: items, targetPath: 'dest' });

        succeed('a.txt');
        fail('b.txt');
        expect(moveCalls()).toEqual(['a.txt', 'b.txt', 'c.txt']);
        succeed('c.txt');

        expect(toast.warning).toHaveBeenCalledWith('2 of 3 items moved. Failed: "b.txt"');
        expect(toast.success).not.toHaveBeenCalled();
        expect(storageApi.list).toHaveBeenCalledWith('');
    });

    it('reloads the tree even when every move fails', () => {
        const items = [file('a.txt'), file('b.txt')];
        facade.onContextAction({ action: 'move', item: items[0], selectedItems: items, targetPath: '/' });

        fail('a.txt');
        fail('b.txt');

        expect(toast.error).toHaveBeenCalledWith('Failed to move selected items');
        expect(storageApi.list).toHaveBeenCalledWith('');
    });

    it('clears the previewed file only when it was actually moved', () => {
        const items = [file('a.txt'), file('b.txt')];
        facade.selectedFile.set(items[1]);
        facade.onContextAction({ action: 'move', item: items[0], selectedItems: items, targetPath: 'dest' });

        succeed('a.txt');
        fail('b.txt');

        expect(facade.selectedFile()).toBe(items[1]);
    });

    it('groups sequentially into the new folder and reloads when mkdir fails', () => {
        const items = [file('a.txt'), file('b.txt')];
        facade.onContextAction({ action: 'group-selected', item: items[0], selectedItems: items });

        expect(storageApi.mkdir).toHaveBeenCalledWith('New Folder');
        expect(moveCalls()).toEqual(['a.txt']);
        fail('a.txt');
        expect(moveCalls()).toEqual(['a.txt', 'b.txt']);
        succeed('b.txt');
        expect(toast.warning).toHaveBeenCalledWith('1 of 2 items grouped into "New Folder". Failed: "a.txt"');
        expect(storageApi.list).toHaveBeenCalledWith('');

        storageApi.list.mockClear();
        storageApi.mkdir.mockReturnValueOnce(throwError(() => new Error('mkdir failed')));
        facade.onContextAction({ action: 'group-selected', item: items[0], selectedItems: items });

        expect(toast.error).toHaveBeenCalledWith('Failed to group items');
        expect(storageApi.list).toHaveBeenCalledWith('');
    });

    it('removes the empty new folder when every grouped move fails, before reloading', () => {
        const items = [file('a.txt'), file('b.txt')];
        facade.onContextAction({ action: 'group-selected', item: items[0], selectedItems: items });

        fail('a.txt');
        fail('b.txt');

        expect(storageApi.delete).toHaveBeenCalledWith(['New Folder']);
        expect(toast.error).toHaveBeenCalledWith('Failed to group items');
        const deleteOrder = storageApi.delete.mock.invocationCallOrder[0];
        const reloadOrder = storageApi.list.mock.invocationCallOrder.at(-1)!;
        expect(deleteOrder).toBeLessThan(reloadOrder);
    });

    it('keeps the new folder when its moves failed on the client but the server has contents in it', () => {
        storageApi.list.mockImplementation((path: string) =>
            of(path === 'New Folder' ? [file('New Folder/a.txt')] : [])
        );
        const items = [file('a.txt'), file('b.txt')];
        facade.onContextAction({ action: 'group-selected', item: items[0], selectedItems: items });

        fail('a.txt');
        fail('b.txt');

        expect(storageApi.list).toHaveBeenCalledWith('New Folder');
        expect(storageApi.delete).not.toHaveBeenCalled();
    });

    it('keeps the new folder when at least one grouped move succeeded', () => {
        const items = [file('a.txt'), file('b.txt')];
        facade.onContextAction({ action: 'group-selected', item: items[0], selectedItems: items });

        succeed('a.txt');
        fail('b.txt');

        expect(storageApi.delete).not.toHaveBeenCalled();
    });
});

describe('StorageTreeFacade loading state', () => {
    it('reports the full-page initial load only until the first successful load', () => {
        const response = new Subject<StorageItem[]>();
        TestBed.configureTestingModule({
            providers: [
                StorageTreeFacade,
                {
                    provide: StorageApiService,
                    useValue: { refreshTick: signal(0), triggerRefresh: vi.fn(), list: vi.fn(() => response) },
                },
                { provide: ToastService, useValue: { error: vi.fn() } },
                { provide: ConfirmationDialogService, useValue: {} },
                { provide: Dialog, useValue: {} },
            ],
        });
        const facade = TestBed.inject(StorageTreeFacade);

        facade.loadTree();
        expect(facade.isInitialLoading()).toBe(true);
        response.next([]);
        response.complete();
        expect(facade.isInitialLoading()).toBe(false);

        const refresh = new Subject<StorageItem[]>();
        TestBed.inject(StorageApiService).list = vi.fn(() => refresh);
        facade.reloadTreePreservingExpansion();
        expect(facade.isLoading()).toBe(true);
        expect(facade.isInitialLoading()).toBe(false);
    });
});

describe('StorageTreeFacade merge refresh', () => {
    let facade: StorageTreeFacade;
    let toast: {
        error: ReturnType<typeof vi.fn>;
        success: ReturnType<typeof vi.fn>;
        warning: ReturnType<typeof vi.fn>;
    };
    let listByPath: Map<string, () => Observable<StorageItem[]>>;
    let storageApi: {
        refreshTick: ReturnType<typeof signal<number>>;
        triggerRefresh: ReturnType<typeof vi.fn>;
        list: ReturnType<typeof vi.fn>;
    };

    function item(name: string, type: 'file' | 'folder', extra: Partial<StorageItem> = {}): StorageItem {
        return { id: name.length, name, path: name, type, ...extra };
    }

    beforeEach(() => {
        listByPath = new Map();
        toast = { error: vi.fn(), success: vi.fn(), warning: vi.fn() };
        storageApi = {
            refreshTick: signal(0),
            triggerRefresh: vi.fn(),
            list: vi.fn((path: string) => listByPath.get(path)?.() ?? of([])),
        };
        TestBed.configureTestingModule({
            providers: [
                StorageTreeFacade,
                { provide: StorageApiService, useValue: storageApi },
                { provide: ToastService, useValue: toast },
                { provide: ConfirmationDialogService, useValue: {} },
                { provide: Dialog, useValue: {} },
            ],
        });
        facade = TestBed.inject(StorageTreeFacade);
    });

    it('keeps expanded folders expanded with refreshed children, and drops children of collapsed ones', () => {
        const oldChild: StorageItem = { name: 'old.csv', path: 'reports/old.csv', type: 'file' };
        facade.treeData.set([
            { ...item('reports', 'folder'), isExpanded: true, children: [oldChild] },
            {
                ...item('archive', 'folder'),
                isExpanded: false,
                children: [{ name: 'x', path: 'archive/x', type: 'file' }],
            },
        ]);
        listByPath.set('', () => of([item('reports', 'folder'), item('archive', 'folder'), item('notes.txt', 'file')]));
        listByPath.set('reports', () => of([item('q1.csv', 'file'), item('q2.csv', 'file')]));

        facade.reloadTreePreservingExpansion();

        const [reports, archive, notes] = facade.treeData();
        expect(reports.isExpanded).toBe(true);
        expect(reports.children?.map((child) => child.path)).toEqual(['reports/q1.csv', 'reports/q2.csv']);
        expect(archive.isExpanded).toBeFalsy();
        expect(archive.children).toBeUndefined();
        expect(notes.path).toBe('notes.txt');
        expect(storageApi.list).not.toHaveBeenCalledWith('archive');
    });

    it('refreshes nested expanded folders level by level', () => {
        facade.treeData.set([
            {
                ...item('a', 'folder'),
                isExpanded: true,
                children: [{ ...item('b', 'folder'), path: 'a/b', isExpanded: true, children: [] }],
            },
        ]);
        listByPath.set('', () => of([item('a', 'folder')]));
        listByPath.set('a', () => of([item('b', 'folder')]));
        listByPath.set('a/b', () => of([item('deep.txt', 'file')]));

        facade.reloadTreePreservingExpansion();

        expect(facade.treeData()[0].children?.[0].children?.map((child) => child.path)).toEqual(['a/b/deep.txt']);
    });

    it('cancels an outdated reload, including its nested requests, so its result never lands', () => {
        facade.treeData.set([{ ...item('reports', 'folder'), isExpanded: true, children: [] }]);
        const olderNested = new Subject<StorageItem[]>();
        const newerRoot = new Subject<StorageItem[]>();
        const rootResponses = [of([item('reports', 'folder')]), newerRoot];
        listByPath.set('', () => rootResponses.shift()!);
        listByPath.set('reports', () => olderNested);

        facade.reloadTreePreservingExpansion();
        expect(olderNested.observed).toBe(true);
        facade.reloadTreePreservingExpansion();

        expect(olderNested.observed).toBe(false);
        newerRoot.next([item('newer.txt', 'file')]);
        newerRoot.complete();
        expect(facade.treeData().map((node) => node.path)).toEqual(['newer.txt']);
        expect(facade.isLoading()).toBe(false);
    });

    it('ignores an error from an outdated refresh', () => {
        const older = new Subject<StorageItem[]>();
        const newer = new Subject<StorageItem[]>();
        const responses = [older, newer];
        listByPath.set('', () => responses.shift()!);

        facade.loadTree();
        facade.reloadTreePreservingExpansion();
        expect(older.observed).toBe(false);
        older.error(new Error('late failure'));

        expect(facade.error()).toBeNull();
        expect(toast.error).not.toHaveBeenCalled();
        expect(facade.isLoading()).toBe(true);
    });

    it('keeps the previous children of a sub-level whose request failed', () => {
        const kept: StorageItem = { name: 'kept.csv', path: 'reports/kept.csv', type: 'file' };
        facade.treeData.set([{ ...item('reports', 'folder'), isExpanded: true, children: [kept] }]);
        listByPath.set('', () => of([item('reports', 'folder')]));
        listByPath.set('reports', () => throwError(() => new Error('sub-level failed')));

        facade.reloadTreePreservingExpansion();

        expect(facade.treeData()[0].children).toEqual([kept]);
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('sets the page error state when the initial load fails', () => {
        listByPath.set('', () => throwError(() => new Error('down')));

        facade.loadTree();

        expect(facade.error()).toBe('Failed to load storage files');
        expect(toast.error).not.toHaveBeenCalled();
        expect(facade.isLoading()).toBe(false);
    });

    it('only toasts when a preserving reload fails, keeping the tree', () => {
        facade.treeData.set([item('notes.txt', 'file')]);
        listByPath.set('', () => throwError(() => new Error('down')));

        facade.reloadTreePreservingExpansion();

        expect(toast.error).toHaveBeenCalledWith('Failed to load storage files');
        expect(facade.error()).toBeNull();
        expect(facade.treeData().map((node) => node.path)).toEqual(['notes.txt']);
        expect(facade.isLoading()).toBe(false);
    });
});

describe('StorageTreeFacade refreshTick', () => {
    it('runs exactly one root list per refresh tick, even though the refresh sets treeData', () => {
        const refreshTick = signal(0);
        let listResponse = 0;
        // Without the untracked() fix the refresh loops synchronously. After 10 calls the mock stops
        // emitting, so treeData stops changing, the loop settles, and the assertion below reports the
        // call count instead of the test worker running out of memory.
        const list = vi.fn((path: string): Observable<StorageItem[]> => {
            listResponse += 1;
            if (path !== '') return of([]);
            if (listResponse > 10) return EMPTY;
            // A new array every time, so every refresh really changes treeData.
            return of([{ name: `f${listResponse}.txt`, path: `f${listResponse}.txt`, type: 'file' }]);
        });
        TestBed.configureTestingModule({
            providers: [
                StorageTreeFacade,
                {
                    provide: StorageApiService,
                    useValue: { refreshTick, triggerRefresh: () => refreshTick.update((tick) => tick + 1), list },
                },
                { provide: ToastService, useValue: { error: vi.fn() } },
                { provide: ConfirmationDialogService, useValue: {} },
                { provide: Dialog, useValue: {} },
            ],
        });
        const facade = TestBed.inject(StorageTreeFacade);
        const rootListCalls = (): number => list.mock.calls.filter(([path]) => path === '').length;
        facade.init({ watchRefreshTick: true });
        for (let flush = 0; flush < 5; flush += 1) TestBed.tick();
        expect(rootListCalls()).toBe(1); // the initial load, and nothing re-triggered by its treeData change

        TestBed.inject(StorageApiService).triggerRefresh();
        for (let flush = 0; flush < 5; flush += 1) TestBed.tick();

        expect(rootListCalls()).toBe(2);
        expect(facade.treeData().length).toBe(1);
    });
});

describe('StorageTreeFacade delete confirmation', () => {
    const recycleBinNotice = 'It moves to the recycle bin, where you can restore it for 7 days.';
    const unused = { used: false, items: [] };
    let facade: StorageTreeFacade;
    let storageApi: { refreshTick: ReturnType<typeof signal<number>>; [key: string]: unknown };
    let confirm: ReturnType<typeof vi.fn>;
    let deleteRequest: ReturnType<typeof vi.fn>;
    let usageRequest: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        confirm = vi.fn(() => of(true));
        deleteRequest = vi.fn(() => of(undefined));
        usageRequest = vi.fn(() => of({ flows: unused, surfaces: unused, agents: unused }));
        storageApi = {
            refreshTick: signal(0),
            triggerRefresh: vi.fn(),
            list: vi.fn(() => of([])),
            delete: deleteRequest,
            usage: usageRequest,
        };

        TestBed.configureTestingModule({
            providers: [
                StorageTreeFacade,
                { provide: StorageApiService, useValue: storageApi },
                { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn(), info: vi.fn() } },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                { provide: RecycleBinSettingsService, useValue: { retentionDays: signal(7) } },
                { provide: Dialog, useValue: {} },
            ],
        });
        facade = TestBed.inject(StorageTreeFacade);
    });

    function deleteFile(): void {
        const item = file('report.txt');
        facade.onContextAction({ action: 'delete', item, selectedItems: [item] });
    }

    function confirmation(): { message: string; type: string } {
        return confirm.mock.calls[0][0] as { message: string; type: string };
    }

    it('keeps the plain message when nothing uses the item', () => {
        deleteFile();

        expect(confirmation().message).toContain('Are you sure you want to delete <strong>report.txt</strong> file?');
        expect(confirmation().message).not.toContain('Used in');
        expect(confirmation().type).toBe('danger');
    });

    it('names the flows that use the item, escaped, and warns that restoring does not relink', () => {
        usageRequest.mockReturnValue(
            of({
                flows: {
                    used: true,
                    items: [
                        { id: 1, name: 'Sales' },
                        { id: 2, name: '<b>x</b>' },
                    ],
                },
                surfaces: unused,
                agents: unused,
            })
        );

        deleteFile();

        expect(confirmation().message).toBe(
            `Are you sure you want to delete <strong>report.txt</strong> file? ${recycleBinNotice}` +
                '<br><br>Used in flows: <strong>Sales</strong>, <strong>&lt;b&gt;x&lt;/b&gt;</strong>.' +
                '<br>Deleting will remove it from these, and restoring it from the recycle bin will not add it back.'
        );
        expect(confirmation().type).toBe('warning');
    });

    it('lists every name when there are exactly five', () => {
        const items = [1, 2, 3, 4, 5].map((id) => ({ id, name: `Flow ${id}` }));
        usageRequest.mockReturnValue(of({ flows: { used: true, items }, surfaces: unused, agents: unused }));

        deleteFile();

        expect(confirmation().message).toContain('<strong>Flow 5</strong>.');
        expect(confirmation().message).not.toContain('more');
    });

    it('shows the first five names and counts one more', () => {
        const items = [1, 2, 3, 4, 5, 6].map((id) => ({ id, name: `Flow ${id}` }));
        usageRequest.mockReturnValue(of({ flows: { used: true, items }, surfaces: unused, agents: unused }));

        deleteFile();

        expect(confirmation().message).toContain('<strong>Flow 5</strong> and 1 more.');
        expect(confirmation().message).not.toContain('Flow 6');
    });

    it('counts the rest when many names are used', () => {
        const items = [1, 2, 3, 4, 5, 6, 7].map((id) => ({ id, name: `Flow ${id}` }));
        usageRequest.mockReturnValue(of({ flows: { used: true, items }, surfaces: unused, agents: unused }));

        deleteFile();

        expect(confirmation().message).toContain('<strong>Flow 5</strong> and 2 more.');
    });

    it('gives a nameless line when the item is used but the user cannot view where', () => {
        usageRequest.mockReturnValue(of({ flows: { used: true, items: [] }, surfaces: unused, agents: unused }));

        deleteFile();

        expect(confirmation().message).toContain("Used in flows you can't view.");
        expect(confirmation().type).toBe('warning');
    });

    it('lists every used kind together and skips unused ones', () => {
        usageRequest.mockReturnValue(
            of({
                flows: { used: true, items: [{ id: 1, name: 'Sales' }] },
                surfaces: unused,
                agents: { used: true, items: [] },
            })
        );

        deleteFile();

        expect(confirmation().message).toContain(
            "Used in flows: <strong>Sales</strong>.<br>Used in agents you can't view."
        );
        expect(confirmation().message).not.toContain('surfaces');
    });

    it('uses plural wording and checks every path for a bulk delete', () => {
        usageRequest.mockReturnValue(of({ flows: { used: true, items: [] }, surfaces: unused, agents: unused }));
        const items = [file('a.txt'), file('b.txt')];

        facade.onContextAction({ action: 'delete-selected', item: items[0], selectedItems: items });

        expect(usageRequest).toHaveBeenCalledWith(['a.txt', 'b.txt']);
        expect(confirmation().message).toContain('restoring them from the recycle bin will not add them back.');
    });

    it('still asks the plain question and deletes on confirm when the usage check fails', () => {
        usageRequest.mockReturnValue(throwError(() => new Error('usage failed')));

        deleteFile();

        expect(confirmation().message).toContain('Are you sure you want to delete <strong>report.txt</strong> file?');
        expect(confirmation().message).not.toContain('Used in');
        expect(deleteRequest).toHaveBeenCalledWith(['report.txt']);
    });

    it('does not delete when the warning is declined', () => {
        usageRequest.mockReturnValue(of({ flows: { used: true, items: [] }, surfaces: unused, agents: unused }));
        confirm.mockReturnValue(of(false));

        deleteFile();

        expect(deleteRequest).not.toHaveBeenCalled();
    });

    it('opens one dialog when delete is triggered again while the usage check is pending', () => {
        const pendingUsage = new Subject<unknown>();
        usageRequest.mockReturnValue(pendingUsage);

        deleteFile();
        deleteFile();
        pendingUsage.next({ flows: unused, surfaces: unused, agents: unused });
        pendingUsage.complete();

        expect(confirm).toHaveBeenCalledTimes(1);
        expect(deleteRequest).toHaveBeenCalledTimes(1);
    });

    it('allows deleting again once the previous confirmation has closed', () => {
        deleteFile();
        deleteFile();

        expect(confirm).toHaveBeenCalledTimes(2);
    });
});
