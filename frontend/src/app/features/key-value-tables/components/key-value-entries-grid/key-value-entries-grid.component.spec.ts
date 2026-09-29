import { formatDate } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { ConfirmationDialogService } from '@shared/components';
import { DATE_TIME_FORMAT_24H } from '@shared/constants';
import { NEVER, Observable, of, Subject, throwError } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { KeyValueTable, KeyValueTableEntry, KeyValueTableEntryListItem } from '../../models/key-value-table.model';
import { KeyValueTablesApiService } from '../../services/key-value-tables-api.service';
import { FAKE_MONACO, useFakeJsonEditor } from '../../testing/fake-json-editor.component';
import { KeyValueEntriesGridComponent } from './key-value-entries-grid.component';

// AG Grid in jsdom is slow to start on a loaded machine.
vi.setConfig({ testTimeout: 20000 });

const TABLE: KeyValueTable = {
    id: 1,
    name: 'profiles',
    description: '',
    entry_count: 0,
    created_at: '2026-09-24T00:00:00Z',
    updated_at: '2026-09-24T00:00:00Z',
};

const RUN_ENTRY: KeyValueTableEntryListItem = {
    id: 11,
    table: 1,
    key: 'profile_42',
    value_preview: '{"plan": "pro"}',
    value_truncated: false,
    created_at: '2026-09-27T12:00:00Z',
    // Midday UTC, so the calendar day is the same in every test-runner timezone.
    updated_at: '2026-09-27T12:00:00Z',
    updated_by_session: 123,
    updated_by_graph: 5,
    updated_by_graph_name: 'Customer onboarding',
};
const RUN_ENTRY_FULL: KeyValueTableEntry = {
    id: 11,
    table: 1,
    key: 'profile_42',
    value: { plan: 'pro' },
    created_at: RUN_ENTRY.created_at,
    updated_at: RUN_ENTRY.updated_at,
    updated_by_session: 123,
    updated_by_graph: 5,
    updated_by_graph_name: 'Customer onboarding',
};
const HAND_EDITED_ENTRY: KeyValueTableEntryListItem = {
    ...RUN_ENTRY,
    id: 12,
    key: 'manual',
    updated_by_session: null,
    updated_by_graph: null,
    updated_by_graph_name: null,
};

// jsdom has no ResizeObserver; app-button's overflow directive and AG Grid only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

// jsdom has no layout: offsetParent is null, every rect is zero and nothing counts as visible. AG Grid positions
// the value editor popup against the offset parent, and closes it once its cell looks gone (a zero rect).
function stubLayout(): () => void {
    const offsetParent = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetParent');
    Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
        configurable: true,
        get(this: HTMLElement) {
            return this.parentElement;
        },
    });
    const checkVisibility =
        'checkVisibility' in Element.prototype
            ? vi.spyOn(Element.prototype, 'checkVisibility').mockReturnValue(true)
            : null;
    const rect = vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 100, 40));
    return () => {
        if (offsetParent) Object.defineProperty(HTMLElement.prototype, 'offsetParent', offsetParent);
        checkVisibility?.mockRestore();
        rect.mockRestore();
    };
}

interface EntriesQuery {
    table: number;
    search: string;
    ordering: string;
    offset: number;
}
type EntriesPage = { count: number; next: null; previous: null; results: KeyValueTableEntryListItem[] };

interface RenderOptions {
    canCreate?: boolean;
    canUpdate?: boolean;
    canDelete?: boolean;
    entries?: KeyValueTableEntryListItem[];
    getEntries?: (query: EntriesQuery) => Observable<EntriesPage>;
    getEntry?: (id: number) => Observable<KeyValueTableEntry>;
    createEntry?: (body: unknown) => Observable<KeyValueTableEntry>;
    updateEntry?: (id: number, body: unknown) => Observable<KeyValueTableEntry>;
}

function renderGrid(options: RenderOptions = {}) {
    const getEntries = vi.fn(
        options.getEntries ??
            ((query: EntriesQuery) => {
                const results = query.table === 1 ? (options.entries ?? [RUN_ENTRY, HAND_EDITED_ENTRY]) : [];
                return of({ count: results.length, next: null, previous: null, results });
            })
    );
    const api = {
        getEntries,
        getEntry: vi.fn(options.getEntry ?? (() => of(RUN_ENTRY_FULL))),
        createEntry: vi.fn(options.createEntry ?? (() => NEVER)),
        updateEntry: vi.fn(options.updateEntry ?? (() => NEVER)),
        deleteEntry: vi.fn(() => of(undefined)),
    };
    const confirmDelete = vi.fn(() => of(true));
    // jsdom cannot load Monaco: the value editor gets a stand-in that binds keys the way Monaco does.
    vi.stubGlobal('monaco', FAKE_MONACO);
    useFakeJsonEditor();
    TestBed.configureTestingModule({
        providers: [
            provideRouter([]),
            { provide: KeyValueTablesApiService, useValue: api },
            { provide: ConfirmationDialogService, useValue: { confirmDelete } },
        ],
    });
    const toastError = vi.spyOn(TestBed.inject(ToastService), 'error');
    const fixture = TestBed.createComponent(KeyValueEntriesGridComponent);
    fixture.componentRef.setInput('table', TABLE);
    fixture.componentRef.setInput('canCreate', options.canCreate ?? false);
    fixture.componentRef.setInput('canUpdate', options.canUpdate ?? false);
    fixture.componentRef.setInput('canDelete', options.canDelete ?? false);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    return { fixture, element, api, confirmDelete, toastError };
}

// AG Grid renders, starts and stops editing across a few macrotasks.
async function settle(fixture: { detectChanges: () => void }): Promise<void> {
    for (let round = 0; round < 4; round++) {
        fixture.detectChanges();
        await new Promise((resolve) => setTimeout(resolve));
    }
    fixture.detectChanges();
}

function cell(element: HTMLElement, rowId: string, colId: string): HTMLElement | null {
    return element.querySelector<HTMLElement>(`.ag-row[row-id="${rowId}"] [col-id="${colId}"]`);
}

describe('KeyValueEntriesGridComponent rows', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('links a run-written entry to its session as "<Flow name>, Session #<id>"', async () => {
        const { fixture, element } = renderGrid({ entries: [RUN_ENTRY] });
        await settle(fixture);
        const link = cell(element, '11', 'session')?.querySelector<HTMLAnchorElement>('a.entries-grid__session-link');
        expect(link?.textContent?.trim()).toBe('Customer onboarding, Session #123');
        expect(link?.getAttribute('href')).toBe('/graph/5/session/123');
    });

    it('shows a muted "Manual edit" for a hand-edited entry', async () => {
        const { fixture, element } = renderGrid({ entries: [HAND_EDITED_ENTRY] });
        await settle(fixture);
        const modifiedBy = cell(element, '12', 'session');
        expect(modifiedBy?.querySelector('a')).toBeNull();
        const manualEdit = modifiedBy?.querySelector('.entries-grid__manual-edit');
        expect(manualEdit?.textContent?.trim()).toBe('Manual edit');
        expect(manualEdit?.getAttribute('title')).toBe(
            'Edited by hand, or written by a session that was later deleted'
        );
    });

    it('shows the value preview, with an ellipsis when the server cut it', async () => {
        const { fixture, element } = renderGrid({
            entries: [RUN_ENTRY, { ...HAND_EDITED_ENTRY, value_preview: '"long', value_truncated: true }],
        });
        await settle(fixture);
        expect(cell(element, '11', 'value')?.textContent?.trim()).toBe('{"plan": "pro"}');
        expect(cell(element, '12', 'value')?.textContent?.trim()).toBe('"long…');
    });

    it('uses the app date-time format for Updated', async () => {
        const { fixture, element } = renderGrid({ entries: [RUN_ENTRY] });
        await settle(fixture);
        expect(cell(element, '11', 'updated_at')?.textContent?.trim()).toBe(
            formatDate(RUN_ENTRY.updated_at, DATE_TIME_FORMAT_24H, 'en-US')
        );
    });
});

function keydown(target: Element | null | undefined, key: string, init: KeyboardEventInit = {}): void {
    target?.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }));
}

function type(field: HTMLInputElement | HTMLTextAreaElement | null, text: string): void {
    if (!field) return;
    field.value = text;
    field.dispatchEvent(new Event('input', { bubbles: true }));
}

// A real double-click focuses the cell on its first press; jsdom does not, so focus it first.
async function openEditor(fixture: { detectChanges: () => void }, target: HTMLElement | null): Promise<void> {
    target?.focus();
    target?.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, detail: 2 }));
    await settle(fixture);
}

// The key editor sits in its cell, or in a popup over it while it shows an error.
function keyEditor(): HTMLInputElement | null {
    return document.querySelector<HTMLInputElement>('app-entry-cell-editor input');
}

function editorError(field: HTMLElement | null): string | undefined {
    const describedBy = field?.getAttribute('aria-describedby');
    return describedBy ? document.getElementById(describedBy)?.textContent?.trim() : undefined;
}

// The value editor is a popup, which AG Grid may attach outside the cell: the JSON editor's text, and the group
// around it that carries the loading state and the hint or error.
function valueEditor(): HTMLTextAreaElement | null {
    return document.querySelector<HTMLTextAreaElement>('app-entry-cell-editor app-json-editor textarea');
}

function valueEditorGroup(): HTMLElement | null {
    return document.querySelector<HTMLElement>('app-entry-cell-editor [role="group"]');
}

function badRequest(message: string): HttpErrorResponse {
    return new HttpErrorResponse({ status: 400, error: { message } });
}

describe('KeyValueEntriesGridComponent in-place editing', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('renames a key on Enter', async () => {
        const saved = { ...RUN_ENTRY_FULL, key: 'profile_43' };
        const { fixture, element, api } = renderGrid({ canUpdate: true, updateEntry: () => of(saved) });
        await settle(fixture);
        await openEditor(fixture, cell(element, '11', 'key'));

        type(keyEditor(), 'profile_43');
        keydown(keyEditor(), 'Enter');
        await settle(fixture);

        expect(api.updateEntry).toHaveBeenCalledWith(11, { key: 'profile_43' });
        expect(keyEditor()).toBeNull();
        // Reloaded, so the row shows the server's own key and preview.
        expect(api.getEntries).toHaveBeenCalledTimes(2);
    });

    it('cancels a key edit on Escape', async () => {
        const { fixture, element, api } = renderGrid({ canUpdate: true });
        await settle(fixture);
        await openEditor(fixture, cell(element, '11', 'key'));

        type(keyEditor(), 'other');
        keydown(keyEditor(), 'Escape');
        await settle(fixture);

        expect(api.updateEntry).not.toHaveBeenCalled();
        expect(keyEditor()).toBeNull();
        expect(cell(element, '11', 'key')?.textContent).toContain('profile_42');
    });

    it('does not edit without update permission', async () => {
        const { fixture, element } = renderGrid({ canUpdate: false });
        await settle(fixture);
        await openEditor(fixture, cell(element, '11', 'key'));
        expect(keyEditor()).toBeNull();
    });

    it('loads the full value into the editor, keeps Enter for new lines and saves on Ctrl+Enter', async () => {
        onTestFinished(stubLayout());
        const saved = { ...RUN_ENTRY_FULL, value: { plan: 'team' } };
        const { fixture, element, api } = renderGrid({ canUpdate: true, updateEntry: () => of(saved) });
        await settle(fixture);
        await openEditor(fixture, cell(element, '11', 'value'));

        expect(api.getEntry).toHaveBeenCalledWith(11);
        expect(valueEditor()?.value).toBe('{\n  "plan": "pro"\n}');

        type(valueEditor(), '{\n  "plan": "team"\n}');
        keydown(valueEditor(), 'Enter');
        await settle(fixture);
        expect(valueEditor()).not.toBeNull();
        expect(api.updateEntry).not.toHaveBeenCalled();

        keydown(valueEditor(), 'Enter', { ctrlKey: true });
        await settle(fixture);
        expect(api.updateEntry).toHaveBeenCalledWith(11, { value: { plan: 'team' } });
        expect(valueEditor()).toBeNull();
    });

    it('saves the value on Tab, as on Ctrl+Enter', async () => {
        onTestFinished(stubLayout());
        const saved = { ...RUN_ENTRY_FULL, value: { plan: 'team' } };
        const { fixture, element, api } = renderGrid({ canUpdate: true, updateEntry: () => of(saved) });
        await settle(fixture);
        await openEditor(fixture, cell(element, '11', 'value'));

        type(valueEditor(), '{"plan": "team"}');
        keydown(valueEditor(), 'Tab');
        await settle(fixture);
        expect(api.updateEntry).toHaveBeenCalledWith(11, { value: { plan: 'team' } });
        expect(valueEditor()).toBeNull();
    });

    it('shows a loading state until the full value arrives', async () => {
        onTestFinished(stubLayout());
        const full = new Subject<KeyValueTableEntry>();
        const { fixture, element } = renderGrid({ canUpdate: true, getEntry: () => full });
        await settle(fixture);
        await openEditor(fixture, cell(element, '11', 'value'));

        expect(valueEditor()).toBeNull();
        expect(valueEditorGroup()?.getAttribute('aria-busy')).toBe('true');
        expect(valueEditorGroup()?.textContent).toContain('Loading…');
        full.next(RUN_ENTRY_FULL);
        await settle(fixture);
        expect(valueEditorGroup()?.getAttribute('aria-busy')).toBe('false');
        expect(valueEditor()?.value).toBe('{\n  "plan": "pro"\n}');
    });

    it('does not fetch the value again after saving it', async () => {
        onTestFinished(stubLayout());
        const saved = { ...RUN_ENTRY_FULL, value: { plan: 'team' }, updated_at: '2026-09-28T12:00:00Z' };
        let row = RUN_ENTRY;
        const { fixture, element, api } = renderGrid({
            canUpdate: true,
            getEntries: () => of({ count: 1, next: null, previous: null, results: [row] }),
            updateEntry: () => {
                row = { ...RUN_ENTRY, value_preview: '{"plan": "team"}', updated_at: saved.updated_at };
                return of(saved);
            },
        });
        await settle(fixture);
        await openEditor(fixture, cell(element, '11', 'value'));
        type(valueEditor(), '{"plan": "team"}');
        keydown(valueEditor(), 'Enter', { ctrlKey: true });
        await settle(fixture);

        await openEditor(fixture, cell(element, '11', 'value'));
        expect(api.getEntry).toHaveBeenCalledOnce();
        expect(valueEditor()?.value).toBe('{\n  "plan": "team"\n}');
    });

    it('keeps invalid JSON in the editor with the reason, without saving', async () => {
        onTestFinished(stubLayout());
        const { fixture, element, api, toastError } = renderGrid({ canUpdate: true });
        await settle(fixture);
        await openEditor(fixture, cell(element, '11', 'value'));

        type(valueEditor(), '{oops');
        keydown(valueEditor(), 'Enter', { ctrlKey: true });
        await settle(fixture);

        expect(api.updateEntry).not.toHaveBeenCalled();
        expect(toastError).toHaveBeenCalledWith('Value must be valid JSON');
        expect(valueEditor()?.value).toBe('{oops');
        expect(document.querySelector('.entry-editor__error')?.textContent).toContain('Value must be valid JSON');
    });

    it('puts a rejected key rename back into the key cell with the server reason', async () => {
        onTestFinished(stubLayout());
        const { fixture, element, toastError } = renderGrid({
            canUpdate: true,
            updateEntry: () => throwError(() => badRequest('key: An entry with this key already exists.')),
        });
        await settle(fixture);
        await openEditor(fixture, cell(element, '11', 'key'));

        type(keyEditor(), 'manual');
        keydown(keyEditor(), 'Enter');
        await settle(fixture);

        expect(toastError).toHaveBeenCalled();
        const editor = keyEditor();
        expect(editor?.value).toBe('manual');
        expect(editor?.getAttribute('aria-invalid')).toBe('true');
        expect(editorError(editor)).toBe('An entry with this key already exists.');
    });

    it('does not let a row be edited again until its save has landed', async () => {
        const saved = new Subject<KeyValueTableEntry>();
        const { fixture, element, api } = renderGrid({ canUpdate: true, updateEntry: () => saved });
        await settle(fixture);
        await openEditor(fixture, cell(element, '11', 'key'));
        type(keyEditor(), 'profile_43');
        keydown(keyEditor(), 'Enter');
        await settle(fixture);

        await openEditor(fixture, cell(element, '11', 'key'));
        expect(keyEditor()).toBeNull();
        expect(cell(element, '11', 'key')?.classList).toContain('entries-grid__cell--saving');
        expect(cell(element, '11', 'value')?.classList).toContain('entries-grid__cell--saving');

        saved.next({ ...RUN_ENTRY_FULL, key: 'profile_43' });
        await settle(fixture);
        expect(api.getEntries).toHaveBeenCalledTimes(2);
        expect(cell(element, '11', 'key')?.classList).not.toContain('entries-grid__cell--saving');
        await openEditor(fixture, cell(element, '11', 'key'));
        expect(keyEditor()).not.toBeNull();
    });

    it('keeps a row locked until its last overlapping save and the reload after it have landed', async () => {
        onTestFinished(stubLayout());
        const keySave = new Subject<KeyValueTableEntry>();
        const valueSave = new Subject<KeyValueTableEntry>();
        let listed = RUN_ENTRY;
        let serverValue: unknown = { plan: 'pro' };
        const { fixture, element, api } = renderGrid({
            canUpdate: true,
            getEntries: () => of({ count: 1, next: null, previous: null, results: [listed] }),
            getEntry: () =>
                of({ ...RUN_ENTRY_FULL, key: listed.key, value: serverValue, updated_at: listed.updated_at }),
            updateEntry: (_id, body) => ('key' in (body as object) ? keySave : valueSave),
        });
        const locked = () => cell(element, '11', 'value')?.classList.contains('entries-grid__cell--saving');
        await settle(fixture);

        // Tab from the renamed key goes on to the value while the rename is on its way; both saves are now pending.
        await openEditor(fixture, cell(element, '11', 'key'));
        type(keyEditor(), 'profile_43');
        keydown(keyEditor(), 'Tab');
        await settle(fixture);
        type(valueEditor(), '{"plan": "team"}');
        keydown(valueEditor(), 'Enter', { ctrlKey: true });
        await settle(fixture);
        expect(api.updateEntry).toHaveBeenCalledTimes(2);

        // The rename and its reload land first: the value save is still out, so the row stays locked.
        listed = { ...RUN_ENTRY, key: 'profile_43', updated_at: '2026-09-28T12:00:00Z' };
        keySave.next({ ...RUN_ENTRY_FULL, key: 'profile_43', updated_at: listed.updated_at });
        await settle(fixture);
        expect(api.getEntries).toHaveBeenCalledTimes(2);
        expect(locked()).toBe(true);
        await openEditor(fixture, cell(element, '11', 'value'));
        expect(valueEditor()).toBeNull();

        // The value save and its reload land: the row unlocks and shows the saved value, not the rename's copy.
        serverValue = { plan: 'team' };
        listed = { ...listed, value_preview: '{"plan": "team"}', updated_at: '2026-09-28T12:00:01Z' };
        valueSave.next({ ...RUN_ENTRY_FULL, key: 'profile_43', value: serverValue, updated_at: listed.updated_at });
        await settle(fixture);
        expect(api.getEntries).toHaveBeenCalledTimes(3);
        expect(locked()).toBe(false);
        await openEditor(fixture, cell(element, '11', 'value'));
        expect(valueEditor()?.value).toBe('{\n  "plan": "team"\n}');
    });

    it('unlocks the row with a reload when the last overlapping save fails, keeping its text', async () => {
        onTestFinished(stubLayout());
        const keySave = new Subject<KeyValueTableEntry>();
        const valueSave = new Subject<KeyValueTableEntry>();
        let listed = RUN_ENTRY;
        const { fixture, element, api } = renderGrid({
            canUpdate: true,
            getEntries: () => of({ count: 1, next: null, previous: null, results: [listed] }),
            updateEntry: (_id, body) => ('key' in (body as object) ? keySave : valueSave),
        });
        const locked = () => cell(element, '11', 'value')?.classList.contains('entries-grid__cell--saving');
        await settle(fixture);

        await openEditor(fixture, cell(element, '11', 'key'));
        type(keyEditor(), 'profile_43');
        keydown(keyEditor(), 'Tab');
        await settle(fixture);
        type(valueEditor(), '{"plan": "team"}');
        keydown(valueEditor(), 'Enter', { ctrlKey: true });
        await settle(fixture);

        // The rename and its reload land while the value save is still out: the row stays locked.
        listed = { ...RUN_ENTRY, key: 'profile_43', updated_at: '2026-09-28T12:00:00Z' };
        keySave.next({ ...RUN_ENTRY_FULL, key: 'profile_43', updated_at: listed.updated_at });
        await settle(fixture);
        expect(api.getEntries).toHaveBeenCalledTimes(2);
        expect(locked()).toBe(true);

        // The value save fails: a follow-up reload brings the rename and unlocks the row.
        valueSave.error(badRequest('value: Too large.'));
        await settle(fixture);
        expect(api.getEntries).toHaveBeenCalledTimes(3);
        expect(locked()).toBe(false);

        await openEditor(fixture, cell(element, '11', 'value'));
        expect(valueEditor()?.value).toBe('{"plan": "team"}');
        expect(editorError(valueEditorGroup())).toBe('Too large.');
    });

    it('clears an old key error before trying the create again', async () => {
        onTestFinished(stubLayout());
        let attempt = 0;
        const { fixture, element } = renderGrid({
            canCreate: true,
            createEntry: () => {
                attempt += 1;
                return throwError(() =>
                    badRequest(attempt === 1 ? 'key: An entry with this key already exists.' : 'value: Too large.')
                );
            },
        });
        await settle(fixture);
        element.querySelector<HTMLElement>('.entries-grid__header app-button')?.click();
        await settle(fixture);
        type(keyEditor(), 'manual');
        keydown(keyEditor(), 'Enter');
        await settle(fixture);
        expect(editorError(keyEditor())).toBe('An entry with this key already exists.');

        type(keyEditor(), 'other');
        keydown(keyEditor(), 'Enter');
        await settle(fixture);
        expect(cell(element, 'new-entry', 'key')?.querySelector('.entries-grid__cell-error')).toBeNull();
        expect(editorError(valueEditorGroup())).toBe('Too large.');
    });

    // The grid picks the next cell before the rename locks the row. That is safe: each commit sends only its own
    // field, so the value saved next cannot undo the rename.
    it('goes on to the value on Tab from a renamed key, and saves only the value there', async () => {
        onTestFinished(stubLayout());
        const { fixture, element, api } = renderGrid({ canUpdate: true, updateEntry: () => NEVER });
        await settle(fixture);
        await openEditor(fixture, cell(element, '11', 'key'));
        type(keyEditor(), 'profile_43');
        keydown(keyEditor(), 'Tab');
        await settle(fixture);
        expect(api.updateEntry).toHaveBeenCalledWith(11, { key: 'profile_43' });
        expect(valueEditor()?.value).toBe('{\n  "plan": "pro"\n}');

        type(valueEditor(), '{"plan": "team"}');
        keydown(valueEditor(), 'Enter', { ctrlKey: true });
        await settle(fixture);
        expect(api.updateEntry).toHaveBeenLastCalledWith(11, { value: { plan: 'team' } });
    });

    it('keeps invalid JSON committed by a click outside, for the next time the cell opens', async () => {
        onTestFinished(stubLayout());
        const outside = document.body.appendChild(document.createElement('button'));
        onTestFinished(() => outside.remove());
        const { fixture, element, api } = renderGrid({ canUpdate: true });
        await settle(fixture);
        await openEditor(fixture, cell(element, '11', 'value'));
        type(valueEditor(), '{oops');
        // A real click outside: the press closes the popup editor, then focus moves.
        outside.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        outside.focus();
        await settle(fixture);

        expect(api.updateEntry).not.toHaveBeenCalled();
        expect(valueEditor()).toBeNull();
        expect(document.activeElement).toBe(outside);
        expect(cell(element, '11', 'value')?.querySelector('.entries-grid__cell-error')?.textContent).toContain(
            'Value must be valid JSON'
        );

        // Opening another cell first does not throw the rejected edit away.
        await openEditor(fixture, cell(element, '12', 'key'));
        keydown(keyEditor(), 'Escape');
        await settle(fixture);

        await openEditor(fixture, cell(element, '11', 'value'));
        expect(valueEditor()?.value).toBe('{oops');
        expect(editorError(valueEditorGroup())).toBe('Value must be valid JSON');

        keydown(valueEditor(), 'Escape');
        await settle(fixture);
        expect(cell(element, '11', 'value')?.querySelector('.entries-grid__cell-error')).toBeNull();
    });

    it('leaves focus where the user put it when the reload after a rename lands', async () => {
        const reload = new Subject<EntriesPage>();
        let loads = 0;
        const { fixture, element } = renderGrid({
            canUpdate: true,
            getEntries: () => {
                loads += 1;
                return loads === 1 ? of({ count: 1, next: null, previous: null, results: [RUN_ENTRY] }) : reload;
            },
            updateEntry: () => of({ ...RUN_ENTRY_FULL, key: 'profile_43' }),
        });
        await settle(fixture);
        await openEditor(fixture, cell(element, '11', 'key'));
        type(keyEditor(), 'profile_43');
        keydown(keyEditor(), 'Enter');
        await settle(fixture);

        const search = element.querySelector<HTMLInputElement>('.entries-grid__header app-search input');
        search?.focus();
        reload.next({ count: 1, next: null, previous: null, results: [{ ...RUN_ENTRY, key: 'profile_43' }] });
        await settle(fixture);
        expect(document.activeElement).toBe(search);
    });
});

describe('KeyValueEntriesGridComponent new entry row', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    function addButton(element: HTMLElement): HTMLElement | null {
        return element.querySelector<HTMLElement>('.entries-grid__header app-button');
    }

    it('is offered only with create permission', async () => {
        const { fixture, element } = renderGrid({ canCreate: false });
        await settle(fixture);
        expect(addButton(element)).toBeNull();
    });

    it('opens an empty row at the top with its key in edit mode', async () => {
        const { fixture, element } = renderGrid({ canCreate: true });
        await settle(fixture);
        addButton(element)?.click();
        await settle(fixture);

        expect(element.querySelector('.ag-row[row-index="0"]')?.getAttribute('row-id')).toBe('new-entry');
        expect(keyEditor()?.placeholder).toBe('New entry — removed if left empty');
    });

    it('creates the entry when its key is committed, with the default null value', async () => {
        const created = { ...RUN_ENTRY_FULL, id: 99, key: 'fresh', value: null };
        const { fixture, element, api } = renderGrid({ canCreate: true, createEntry: () => of(created) });
        await settle(fixture);
        addButton(element)?.click();
        await settle(fixture);

        type(keyEditor(), 'fresh');
        keydown(keyEditor(), 'Enter');
        await settle(fixture);

        expect(api.createEntry).toHaveBeenCalledWith({ table: 1, key: 'fresh', value: null });
        expect(element.querySelector('[row-id="new-entry"]')).toBeNull();
        // Reloaded, so the new entry shows up where the server sorts it.
        expect(api.getEntries).toHaveBeenCalledTimes(2);
    });

    it('disappears when left empty', async () => {
        const { fixture, element, api } = renderGrid({ canCreate: true });
        await settle(fixture);
        addButton(element)?.click();
        await settle(fixture);

        keydown(keyEditor(), 'Escape');
        await settle(fixture);

        expect(element.querySelector('[row-id="new-entry"]')).toBeNull();
        expect(api.createEntry).not.toHaveBeenCalled();
    });

    it('is only ever one row', async () => {
        const { fixture, element } = renderGrid({ canCreate: true });
        await settle(fixture);
        addButton(element)?.click();
        await settle(fixture);
        type(keyEditor(), 'half');
        addButton(element)?.click();
        await settle(fixture);

        expect(element.querySelectorAll('.ag-row[row-id="new-entry"]')).toHaveLength(1);
    });

    function rejectingGrid() {
        return renderGrid({
            canCreate: true,
            createEntry: () => throwError(() => badRequest('key: An entry with this key already exists.')),
        });
    }

    it('keeps the row and reopens its key with the reason when the server rejects the key', async () => {
        onTestFinished(stubLayout());
        const { fixture, element } = rejectingGrid();
        await settle(fixture);
        addButton(element)?.click();
        await settle(fixture);
        type(keyEditor(), 'manual');
        keydown(keyEditor(), 'Enter');
        await settle(fixture);

        expect(element.querySelector('[row-id="new-entry"]')).not.toBeNull();
        expect(keyEditor()?.value).toBe('manual');
        expect(editorError(keyEditor())).toBe('An entry with this key already exists.');
    });

    it('drops the row on Escape after a rejected create, without sending it again', async () => {
        onTestFinished(stubLayout());
        const { fixture, element, api } = rejectingGrid();
        await settle(fixture);
        addButton(element)?.click();
        await settle(fixture);
        type(keyEditor(), 'manual');
        keydown(keyEditor(), 'Enter');
        await settle(fixture);

        keydown(keyEditor(), 'Escape');
        await settle(fixture);
        expect(element.querySelector('[row-id="new-entry"]')).toBeNull();
        expect(api.createEntry).toHaveBeenCalledOnce();
    });

    it('drops the row on Escape in the value after Tab from the key, creating nothing', async () => {
        onTestFinished(stubLayout());
        const { fixture, element, api } = renderGrid({ canCreate: true });
        await settle(fixture);
        addButton(element)?.click();
        await settle(fixture);
        type(keyEditor(), 'fresh');
        keydown(keyEditor(), 'Tab');
        await settle(fixture);
        expect(valueEditor()).not.toBeNull();

        keydown(valueEditor(), 'Escape');
        await settle(fixture);
        expect(element.querySelector('[row-id="new-entry"]')).toBeNull();
        expect(api.createEntry).not.toHaveBeenCalled();
    });

    it('lets focus go after a create rejected on a click outside, keeps the error and retries on the next commit', async () => {
        onTestFinished(stubLayout());
        const outside = document.body.appendChild(document.createElement('button'));
        onTestFinished(() => outside.remove());
        const { fixture, element, api } = rejectingGrid();
        await settle(fixture);
        addButton(element)?.click();
        await settle(fixture);
        type(keyEditor(), 'manual');
        outside.focus();
        await settle(fixture);

        expect(api.createEntry).toHaveBeenCalledOnce();
        expect(keyEditor()).toBeNull();
        expect(document.activeElement).toBe(outside);
        expect(cell(element, 'new-entry', 'key')?.querySelector('.entries-grid__cell-error')?.textContent).toContain(
            'An entry with this key already exists.'
        );

        await openEditor(fixture, cell(element, 'new-entry', 'key'));
        expect(keyEditor()?.value).toBe('manual');
        keydown(keyEditor(), 'Enter');
        await settle(fixture);
        expect(api.createEntry).toHaveBeenCalledTimes(2);
    });
});

describe('KeyValueEntriesGridComponent keyboard', () => {
    let writeText: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        writeText = vi.fn(() => Promise.resolve());
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    });
    afterEach(() => {
        vi.unstubAllGlobals();
        Reflect.deleteProperty(navigator, 'clipboard');
    });

    it('copies a key and the full value with Ctrl/Cmd+C on their cells, for read-only users too', async () => {
        const { fixture, element, api } = renderGrid({ entries: [RUN_ENTRY] });
        await settle(fixture);

        keydown(cell(element, '11', 'key'), 'c', { ctrlKey: true });
        await settle(fixture);
        expect(writeText).toHaveBeenLastCalledWith('profile_42');

        keydown(cell(element, '11', 'value'), 'c', { metaKey: true });
        await settle(fixture);
        expect(api.getEntry).toHaveBeenCalledWith(11);
        expect(writeText).toHaveBeenLastCalledWith('{\n  "plan": "pro"\n}');
    });

    it("shows the server's reason when the value to copy cannot be fetched", async () => {
        const { fixture, element, toastError } = renderGrid({
            entries: [RUN_ENTRY],
            getEntry: () => throwError(() => new HttpErrorResponse({ status: 404, error: { message: 'Not found.' } })),
        });
        await settle(fixture);
        keydown(cell(element, '11', 'value'), 'c', { ctrlKey: true });
        await settle(fixture);
        expect(toastError).toHaveBeenCalledWith('Not found.', 3000, 'top-right');
        expect(writeText).not.toHaveBeenCalled();
    });

    it('deletes with Enter on the actions cell, only with delete permission', async () => {
        const { fixture, element, api, confirmDelete } = renderGrid({ canDelete: true, entries: [RUN_ENTRY] });
        await settle(fixture);
        keydown(cell(element, '11', 'actions'), 'Enter');
        await settle(fixture);
        expect(confirmDelete).toHaveBeenCalledWith('profile_42');
        expect(api.deleteEntry).toHaveBeenCalledWith(11);
    });

    it('follows the session link with Enter on the session cell', async () => {
        const { fixture, element } = renderGrid({ entries: [RUN_ENTRY] });
        const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
        await settle(fixture);
        keydown(cell(element, '11', 'session'), 'Enter');
        await settle(fixture);
        expect(navigate).toHaveBeenCalledWith(['/graph', 5, 'session', 123]);
    });

    it('still starts editing an editable cell with Enter', async () => {
        const { fixture, element } = renderGrid({ canUpdate: true, entries: [RUN_ENTRY] });
        await settle(fixture);
        keydown(cell(element, '11', 'key'), 'Enter');
        await settle(fixture);
        expect(keyEditor()?.value).toBe('profile_42');
    });
});

describe('KeyValueEntriesGridComponent delete', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('deletes with a cross after confirmation', async () => {
        const { fixture, element, api, confirmDelete } = renderGrid({ canDelete: true });
        await settle(fixture);
        const cross = cell(element, '11', 'actions')?.querySelector<HTMLButtonElement>('button');
        expect(cross?.querySelector('i.ti-x')).not.toBeNull();

        cross?.click();
        await settle(fixture);
        expect(confirmDelete).toHaveBeenCalledWith('profile_42');
        expect(api.deleteEntry).toHaveBeenCalledWith(11);
    });

    it('has no delete column without delete permission', async () => {
        const { fixture, element } = renderGrid({ canDelete: false });
        await settle(fixture);
        expect(element.querySelector('[col-id="actions"]')).toBeNull();
    });
});

describe('KeyValueEntriesGridComponent sorting', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    function header(element: HTMLElement, colId: string): HTMLElement | null {
        return element.querySelector<HTMLElement>(`.ag-header-cell[col-id="${colId}"]`);
    }

    async function clickHeader(fixture: { detectChanges: () => void }, element: HTMLElement, colId: string) {
        header(element, colId)?.querySelector<HTMLElement>('.ag-header-cell-label')?.click();
        await settle(fixture);
    }

    it('sorts by key ascending by default and shows it as aria-sort', async () => {
        const { fixture, element, api } = renderGrid();
        await settle(fixture);
        expect(api.getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: 'key' }));
        expect(header(element, 'key')?.getAttribute('aria-sort')).toBe('ascending');
        expect(header(element, 'value')?.hasAttribute('aria-sort')).toBe(false);
    });

    it('flips the sorted column and starts a new column ascending, back on page 1', async () => {
        const { fixture, element, api } = renderGrid();
        await settle(fixture);
        fixture.componentInstance.page.set(2);
        await settle(fixture);

        await clickHeader(fixture, element, 'key');
        expect(api.getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: '-key', offset: 0 }));
        await clickHeader(fixture, element, 'updated_at');
        expect(api.getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: 'updated_at' }));
        await clickHeader(fixture, element, 'updated_at');
        expect(api.getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: '-updated_at' }));
        expect(header(element, 'updated_at')?.getAttribute('aria-sort')).toBe('descending');
        // "Modified By" still sorts by the server's `session` ordering.
        expect(header(element, 'session')?.querySelector('.ag-header-cell-text')?.textContent?.trim()).toBe(
            'Modified By'
        );
        await clickHeader(fixture, element, 'session');
        expect(api.getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: 'session' }));
    });

    it('does not sort by value', async () => {
        const { fixture, element, api } = renderGrid();
        await settle(fixture);
        const calls = api.getEntries.mock.calls.length;
        await clickHeader(fixture, element, 'value');
        expect(api.getEntries).toHaveBeenCalledTimes(calls);
    });
});

describe('KeyValueEntriesGridComponent key search', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it('sits in the grid header', async () => {
        const { fixture, element } = renderGrid();
        await settle(fixture);
        expect(element.querySelector('.entries-grid__header app-search input')?.getAttribute('placeholder')).toBe(
            'Search keys...'
        );
    });

    it('sends the settled term, keeps it across a table switch and applies a cleared term at once', () => {
        vi.useFakeTimers();
        const { fixture, api } = renderGrid();

        fixture.componentInstance.searchTerm.set('  profile ');
        fixture.detectChanges();
        vi.advanceTimersByTime(299);
        fixture.detectChanges();
        expect(api.getEntries).not.toHaveBeenCalledWith(expect.objectContaining({ search: 'profile' }));
        vi.advanceTimersByTime(1);
        fixture.detectChanges();
        expect(api.getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ table: 1, search: 'profile' }));

        fixture.componentRef.setInput('table', { ...TABLE, id: 2, name: 'orders' });
        fixture.detectChanges();
        expect(api.getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ table: 2, search: 'profile' }));

        fixture.componentInstance.searchTerm.set('');
        fixture.detectChanges();
        expect(api.getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ search: '' }));
    });
});

describe('KeyValueEntriesGridComponent loading', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('marks the grid busy while a page is on its way, and drops a stale answer', async () => {
        const answers: Subject<EntriesPage>[] = [];
        const { fixture, element } = renderGrid({
            getEntries: () => {
                const answer = new Subject<EntriesPage>();
                answers.push(answer);
                return answer;
            },
        });
        const body = () => element.querySelector('.entries-grid__body');
        await settle(fixture);
        expect(body()?.getAttribute('aria-busy')).toBe('true');

        answers[0].next({ count: 1, next: null, previous: null, results: [RUN_ENTRY] });
        await settle(fixture);
        expect(body()?.getAttribute('aria-busy')).toBe('false');

        fixture.componentInstance.page.set(2);
        await settle(fixture);
        expect(body()?.getAttribute('aria-busy')).toBe('true');
        // Back to page 1 before page 2 answered: page 2's late answer must not land.
        fixture.componentInstance.page.set(1);
        await settle(fixture);
        answers[1].next({ count: 1, next: null, previous: null, results: [HAND_EDITED_ENTRY] });
        await settle(fixture);
        expect(fixture.componentInstance.entries()).toEqual([RUN_ENTRY]);
    });

    it("drops the previous table's rows while the new table loads", async () => {
        const { fixture } = renderGrid({
            getEntries: (query) =>
                query.table === 1 ? of({ count: 1, next: null, previous: null, results: [RUN_ENTRY] }) : NEVER,
        });
        await settle(fixture);
        expect(fixture.componentInstance.entries()).toEqual([RUN_ENTRY]);

        fixture.componentRef.setInput('table', { ...TABLE, id: 2, name: 'orders' });
        fixture.detectChanges();
        expect(fixture.componentInstance.entries()).toEqual([]);
        expect(fixture.componentInstance.totalCount()).toBe(0);
    });
});

describe('KeyValueEntriesGridComponent copy key and value', () => {
    let writeText: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        writeText = vi.fn(() => Promise.resolve());
        // jsdom has no Clipboard API (nor ClipboardItem, so the copy falls back to writeText).
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    });
    afterEach(() => {
        vi.unstubAllGlobals();
        Reflect.deleteProperty(navigator, 'clipboard');
    });

    // The labels name the keyboard shortcut too, since the button is out of reach for Tab.
    function copyButton(element: HTMLElement, ariaLabel: 'Copy key' | 'Copy value'): HTMLButtonElement | null {
        return element.querySelector<HTMLButtonElement>(`app-copy-button button[aria-label="${ariaLabel} (Ctrl+C)"]`);
    }

    it('copies the key, for read-only users too', async () => {
        const { fixture, element } = renderGrid({ entries: [RUN_ENTRY] });
        await settle(fixture);
        copyButton(element, 'Copy key')?.click();
        expect(writeText).toHaveBeenCalledWith('profile_42');
    });

    it('fetches the full value and copies it as indented JSON, for read-only users too', async () => {
        const { fixture, element, api } = renderGrid({ entries: [RUN_ENTRY] });
        await settle(fixture);
        copyButton(element, 'Copy value')?.click();
        await settle(fixture);
        expect(api.getEntry).toHaveBeenCalledWith(11);
        expect(writeText).toHaveBeenCalledWith('{\n  "plan": "pro"\n}');
    });

    it('copies a string value as its raw text, without JSON quotes', async () => {
        const { fixture, element } = renderGrid({
            entries: [RUN_ENTRY],
            getEntry: () => of({ ...RUN_ENTRY_FULL, value: 'hello "world"' }),
        });
        await settle(fixture);
        copyButton(element, 'Copy value')?.click();
        await settle(fixture);
        expect(writeText).toHaveBeenCalledWith('hello "world"');
    });

    it('does not open the editor when Copy is double-clicked', async () => {
        const { fixture, element } = renderGrid({ canUpdate: true, entries: [RUN_ENTRY] });
        await settle(fixture);
        for (const host of element.querySelectorAll('app-copy-button')) {
            host.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, detail: 2 }));
        }
        await settle(fixture);
        expect(element.querySelector('app-entry-cell-editor')).toBeNull();
    });
});
