import { TestBed } from '@angular/core/testing';
import { of, Subject } from 'rxjs';

import { FAKE_MONACO, liveFakeKeybindings, useFakeJsonEditor } from '../../testing/fake-json-editor.component';
import { EntryCellEditorComponent, EntryCellEditorParams } from './entry-cell-editor.component';

// AG Grid renders the editor, then attaches it (focus) and lets Monaco come up after a render.
async function attach(fixture: { detectChanges: () => void; whenStable: () => Promise<unknown> }): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
}

// Once per test, before any editor is created: TestBed takes no overrides after that.
function setUp(): void {
    vi.stubGlobal('monaco', FAKE_MONACO);
    useFakeJsonEditor();
}

function tearDown(): void {
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
}

function renderEditor(params: Partial<EntryCellEditorParams>) {
    const stopEditing = vi.fn();
    // The cell's key handling (Tab, Esc), which the popup hands keys to.
    const onKeyDown = vi.fn<(event: KeyboardEvent) => void>();
    const committed = vi.fn();
    const fixture = TestBed.createComponent(EntryCellEditorComponent);
    const element = fixture.nativeElement as HTMLElement;
    // In the document, as the grid's popup is, so focus can land in it.
    document.body.appendChild(element);
    fixture.componentInstance.agInit({
        multiline: true,
        ariaLabel: 'Value (JSON)',
        placeholder: '',
        error: null,
        text$: of('null'),
        committed,
        stopEditing,
        onKeyDown,
        ...params,
    } as EntryCellEditorParams);
    fixture.detectChanges();
    // Stands in for AG Grid, which listens for keys above the editor.
    const reachedGrid = vi.fn();
    element.addEventListener('keydown', reachedGrid);
    const field = () => element.querySelector<HTMLTextAreaElement>('app-json-editor textarea');
    const group = () => element.querySelector<HTMLElement>('[role="group"]');
    return { fixture, element, field, group, stopEditing, onKeyDown, committed, reachedGrid };
}

function press(target: Element | null, init: KeyboardEventInit): void {
    target?.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init }));
}

describe('EntryCellEditorComponent value JSON editor', () => {
    beforeEach(setUp);
    afterEach(tearDown);

    it('opens the value in the JSON editor and focuses it', async () => {
        const { fixture, field } = renderEditor({ text$: of('{"a": 1}') });
        await attach(fixture);
        expect(field()?.value).toBe('{"a": 1}');
        expect(document.activeElement).toBe(field());
    });

    it('keeps Enter for a new line: the grid never sees it and editing goes on', async () => {
        const { fixture, field, stopEditing, reachedGrid } = renderEditor({});
        await attach(fixture);
        press(field(), { key: 'Enter' });
        expect(stopEditing).not.toHaveBeenCalled();
        expect(reachedGrid).not.toHaveBeenCalled();
    });

    it('commits on Ctrl+Enter and Cmd+Enter, without the grid seeing the key', async () => {
        const { fixture, field, stopEditing, reachedGrid } = renderEditor({});
        await attach(fixture);
        press(field(), { key: 'Enter', ctrlKey: true });
        press(field(), { key: 'Enter', metaKey: true });
        expect(stopEditing).toHaveBeenCalledTimes(2);
        expect(stopEditing).toHaveBeenCalledWith();
        expect(reachedGrid).not.toHaveBeenCalled();
    });

    it('hands Tab, Shift+Tab and Escape, which Monaco would keep, to the cell, which commits or cancels', async () => {
        const { fixture, field, stopEditing, onKeyDown, reachedGrid } = renderEditor({});
        await attach(fixture);
        press(field(), { key: 'Tab' });
        press(field(), { key: 'Tab', shiftKey: true });
        press(field(), { key: 'Escape' });
        const keys = onKeyDown.mock.calls.map(([event]) => [event.key, event.shiftKey]);
        expect(keys).toEqual([
            ['Tab', false],
            ['Tab', true],
            ['Escape', false],
        ]);
        // Once each: the real key stops at Monaco.
        expect(reachedGrid).not.toHaveBeenCalled();
        // The params' stopEditing would commit: its argument only suppresses navigation.
        expect(stopEditing).not.toHaveBeenCalled();
    });

    it('returns what the editor holds, also edits it never reported (made while it formatted its value)', async () => {
        const { fixture, field } = renderEditor({});
        await attach(fixture);
        const textarea = field();
        if (!textarea) throw new Error('no editor');
        // No input event: the JSON editor ignores changes while it formats the value it opened with.
        textarea.value = '{"c": 3}';
        expect(fixture.componentInstance.getValue()).toBe('{"c": 3}');
    });

    it("shows a rejected empty value as empty, not as the JSON editor's {}, so it is what a commit saves", async () => {
        const { fixture, field } = renderEditor({ text$: of('') });
        await attach(fixture);
        expect(field()?.value).toBe('');
        expect(fixture.componentInstance.getValue()).toBe('');
    });

    it('binds its keys for its own editor only, leaving another Monaco editor alone', async () => {
        const first = renderEditor({});
        const second = renderEditor({});
        await attach(first.fixture);
        await attach(second.fixture);

        // In the first: page-wide bindings would run the newer, second editor's.
        press(first.field(), { key: 'Tab' });
        press(first.field(), { key: 'Enter', ctrlKey: true });
        expect(first.onKeyDown).toHaveBeenCalledTimes(1);
        expect(first.stopEditing).toHaveBeenCalledTimes(1);
        expect(second.onKeyDown).not.toHaveBeenCalled();
        expect(second.stopEditing).not.toHaveBeenCalled();
    });

    it('takes its key bindings with it when it closes', async () => {
        const before = liveFakeKeybindings();
        const { fixture } = renderEditor({});
        await attach(fixture);
        expect(liveFakeKeybindings()).toBe(before + 4);

        fixture.destroy();
        expect(liveFakeKeybindings()).toBe(before);
    });

    it('returns what was typed', async () => {
        const { fixture, field } = renderEditor({});
        await attach(fixture);
        const textarea = field();
        if (!textarea) throw new Error('no editor');
        textarea.value = '{"b": 2}';
        textarea.dispatchEvent(new Event('input'));
        expect(fixture.componentInstance.getValue()).toBe('{"b": 2}');
    });

    it('shows a loading state and cancels a commit until the text has loaded, Esc still reaching the grid', async () => {
        const text$ = new Subject<string>();
        const { fixture, field, group, reachedGrid, stopEditing } = renderEditor({ text$ });
        fixture.componentInstance.afterGuiAttached();
        expect(field()).toBeNull();
        expect(group()?.getAttribute('aria-busy')).toBe('true');
        expect(group()?.textContent).toContain('Loading…');
        expect(document.activeElement).toBe(group());
        expect(fixture.componentInstance.isCancelAfterEnd()).toBe(true);
        press(group(), { key: 'Escape' });
        expect(reachedGrid).toHaveBeenCalledTimes(1);
        // Ctrl+Enter before Monaco is up still commits (a commit the grid then cancels, as nothing loaded).
        press(group(), { key: 'Enter', ctrlKey: true });
        expect(stopEditing).toHaveBeenCalledExactlyOnceWith();

        text$.next('{"a": 1}');
        await attach(fixture);
        expect(group()?.getAttribute('aria-busy')).toBe('false');
        expect(field()?.value).toBe('{"a": 1}');
        expect(fixture.componentInstance.isCancelAfterEnd()).toBe(false);
        expect(fixture.componentInstance.getValue()).toBe('{"a": 1}');
    });

    it('reports whether focus was still in the editor on a commit', async () => {
        const { fixture, committed } = renderEditor({});
        await attach(fixture);
        fixture.componentInstance.isCancelAfterEnd();
        (document.activeElement as HTMLElement | null)?.blur();
        fixture.componentInstance.isCancelAfterEnd();
        expect(committed.mock.calls).toEqual([[true], [false]]);
    });

    it('describes the editor with the key hint', () => {
        const { element, group } = renderEditor({});
        const hint = element.querySelector(`[id="${group()?.getAttribute('aria-describedby')}"]`);
        expect(hint?.textContent?.trim()).toBe('Ctrl+Enter to save · Esc to cancel');
    });

    it('shows why the last commit failed instead of the key hint', () => {
        const { element, group } = renderEditor({ error: 'Value must be valid JSON' });
        const error = element.querySelector(`[id="${group()?.getAttribute('aria-describedby')}"]`);
        expect(error?.textContent?.trim()).toBe('Value must be valid JSON');
        expect(element.querySelector('.entry-editor__error')?.textContent).toContain('Value must be valid JSON');
        expect(element.querySelector('.entry-editor__hint')).toBeNull();
    });
});

describe('EntryCellEditorComponent key input', () => {
    beforeEach(setUp);
    afterEach(tearDown);

    it('is an in-cell input without an error', () => {
        const { fixture, element } = renderEditor({ multiline: false, text$: of('k') });
        expect(fixture.componentInstance.isPopup()).toBe(false);
        expect(element.querySelector('input')?.hasAttribute('aria-describedby')).toBe(false);
    });

    it('shows the placeholder and the server reason as described text', () => {
        const { fixture, element } = renderEditor({
            multiline: false,
            placeholder: 'New entry — removed if left empty',
            error: 'An entry with this key already exists.',
            text$: of('manual'),
        });
        const input = element.querySelector('input');
        expect(input?.value).toBe('manual');
        expect(input?.placeholder).toBe('New entry — removed if left empty');
        expect(input?.getAttribute('aria-invalid')).toBe('true');
        const describedBy = input?.getAttribute('aria-describedby') ?? '';
        expect(element.querySelector(`[id="${describedBy}"]`)?.textContent?.trim()).toBe(
            'An entry with this key already exists.'
        );
        // Shown as text, which needs room: the key editor becomes a popup over its cell.
        expect(fixture.componentInstance.isPopup()).toBe(true);
    });
});
