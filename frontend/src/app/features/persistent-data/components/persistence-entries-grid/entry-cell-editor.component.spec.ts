import { TestBed } from '@angular/core/testing';
import { of, Subject } from 'rxjs';

import { EntryCellEditorComponent, EntryCellEditorParams } from './entry-cell-editor.component';

function renderEditor(params: Partial<EntryCellEditorParams>) {
    const stopEditing = vi.fn();
    const fixture = TestBed.createComponent(EntryCellEditorComponent);
    fixture.componentInstance.agInit({
        multiline: true,
        ariaLabel: 'Value (JSON)',
        placeholder: '',
        error: null,
        text$: of('null'),
        committed: vi.fn(),
        stopEditing,
        ...params,
    } as EntryCellEditorParams);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    // Stands in for AG Grid, which listens for keys above the editor.
    const reachedGrid = vi.fn();
    element.addEventListener('keydown', reachedGrid);
    const textarea = element.querySelector('textarea');
    return { fixture, element, textarea, stopEditing, reachedGrid };
}

function press(target: Element | null, init: KeyboardEventInit): void {
    target?.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init }));
}

describe('EntryCellEditorComponent value textarea', () => {
    it('keeps Enter for a new line: the grid never sees it and editing goes on', () => {
        const { textarea, stopEditing, reachedGrid } = renderEditor({});
        press(textarea, { key: 'Enter' });
        expect(stopEditing).not.toHaveBeenCalled();
        expect(reachedGrid).not.toHaveBeenCalled();
    });

    it('commits on Ctrl+Enter and Cmd+Enter', () => {
        const { textarea, stopEditing } = renderEditor({});
        press(textarea, { key: 'Enter', ctrlKey: true });
        press(textarea, { key: 'Enter', metaKey: true });
        expect(stopEditing).toHaveBeenCalledTimes(2);
        expect(stopEditing).toHaveBeenCalledWith();
    });

    it('leaves Tab and Escape to the grid, which commits or cancels', () => {
        const { textarea, stopEditing, reachedGrid } = renderEditor({});
        press(textarea, { key: 'Tab' });
        press(textarea, { key: 'Escape' });
        expect(reachedGrid).toHaveBeenCalledTimes(2);
        expect(stopEditing).not.toHaveBeenCalled();
    });

    it('is read-only and cancels a commit until the text has loaded', () => {
        const text$ = new Subject<string>();
        const { fixture, textarea } = renderEditor({ text$ });
        expect(textarea?.readOnly).toBe(true);
        expect(fixture.componentInstance.isCancelAfterEnd()).toBe(true);

        text$.next('{"a": 1}');
        fixture.detectChanges();
        expect(textarea?.readOnly).toBe(false);
        expect(fixture.componentInstance.isCancelAfterEnd()).toBe(false);
        expect(fixture.componentInstance.getValue()).toBe('{"a": 1}');
    });

    it('describes the textarea with the key hint', () => {
        const { element, textarea } = renderEditor({});
        const hint = element.querySelector(`[id="${textarea?.getAttribute('aria-describedby')}"]`);
        expect(hint?.textContent?.trim()).toBe('Ctrl+Enter to save · Esc to cancel');
    });

    it('shows why the last commit failed instead of the key hint', () => {
        const { element, textarea } = renderEditor({ error: 'Value must be valid JSON' });
        const error = element.querySelector(`[id="${textarea?.getAttribute('aria-describedby')}"]`);
        expect(error?.textContent?.trim()).toBe('Value must be valid JSON');
        expect(element.querySelector('.entry-editor__error')?.textContent).toContain('Value must be valid JSON');
        expect(element.querySelector('.entry-editor__hint')).toBeNull();
    });
});

describe('EntryCellEditorComponent key input', () => {
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
