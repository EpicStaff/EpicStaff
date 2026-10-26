import { Component, input, Provider } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { FieldChange, NodeDiffStatus } from '../../utils/diff';
import { provideChangesTabDiff } from '../missing-reference-note/missing-reference-note.testing';
import { DiffFieldMarkChange, DiffFieldMarkComponent } from './diff-field-mark.component';

/** A panel field wrapped in the mark, next to one the diff does not change; and a row marked by a given change. */
@Component({
    imports: [DiffFieldMarkComponent],
    template: `
        <app-diff-field-mark
            id="output-path"
            [diffField]="'output_variable_path'"
        >
            <label>Output Variable Path</label>
            <span>variables.name</span>
        </app-diff-field-mark>
        <app-diff-field-mark
            id="libraries"
            [diffField]="'python_code.libraries'"
        >
            <label>Libraries</label>
        </app-diff-field-mark>
        <div
            id="row"
            appDiffFieldMark
            [diffChange]="rowChange()"
        >
            <span>user_id</span>
        </div>
    `,
})
class PanelFieldsComponent {
    readonly rowChange = input<DiffFieldMarkChange | null>(null);
}

const OUTPUT_PATH_CHANGE: FieldChange = {
    path: 'output_variable_path',
    field: 'output_variable_path',
    status: 'changed',
    current: 'variables.previous_name',
    version: 'variables.name',
};

function onDiff(status: NodeDiffStatus, fields: FieldChange[] = [OUTPUT_PATH_CHANGE]): Provider {
    return provideChangesTabDiff({ status, fields });
}

let fixture: ComponentFixture<PanelFieldsComponent>;

function render(providers: Provider[], rowChange: DiffFieldMarkChange | null = null): void {
    TestBed.configureTestingModule({ providers });
    fixture = TestBed.createComponent(PanelFieldsComponent);
    fixture.componentRef.setInput('rowChange', rowChange);
    fixture.detectChanges();
}

const element = (id: string): HTMLElement => fixture.nativeElement.querySelector(`#${id}`);
/** What a screen reader reads as the element's description. */
const descriptionOf = (id: string): string | null | undefined =>
    document.getElementById(element(id).getAttribute('aria-describedby') ?? '')?.textContent;
const isMarked = (id: string): boolean => element(id).classList.contains('diff-field-mark--shown');
const tooltip = (): HTMLElement | null => document.querySelector('.diff-field-mark__tooltip');
/** The tooltip's current value, struck parts in brackets. */
const tooltipValue = (): string =>
    Array.from(tooltip()!.querySelectorAll<HTMLElement>('.diff-field-mark__tooltip-value > span'))
        .map((part) =>
            part.classList.contains('diff-field-mark__struck') ? `[${part.textContent}]` : part.textContent
        )
        .join('');

function dispatch(id: string, type: string): void {
    element(id).dispatchEvent(new Event(type));
    fixture.detectChanges();
}

describe('DiffFieldMarkComponent', () => {
    it('marks a changed field of a changed node: a focusable, named, described group', () => {
        render([onDiff('changed')]);

        expect(isMarked('output-path')).toBe(true);
        expect(element('output-path').getAttribute('tabindex')).toBe('0');
        expect(element('output-path').getAttribute('role')).toBe('group');
        const name = document.getElementById(element('output-path').getAttribute('aria-labelledby')!);
        expect(name?.textContent).toBe('Restore changes this field');
        expect(descriptionOf('output-path')).toBe('Current canvas: variables.previous_name');
    });

    // The class the wrapped form component draws its value box's border and badge by.
    it('asks the wrapped field to mark its value only while the field is marked', () => {
        render([onDiff('changed')]);

        expect(element('output-path').classList).toContain('diff-value-marked');
        expect(element('libraries').classList).not.toContain('diff-value-marked');
        // A row is marked by the mark itself.
        expect(element('row').classList).not.toContain('diff-value-marked');
    });

    it('adds no reader-visible element to a marked row: the badge words go into the description', () => {
        render([onDiff('changed', [])], { current: 'variables.user', version: 'variables.account' });

        expect(element('row').hasAttribute('role')).toBe(false);
        const readerVisible = Array.from(element('row').children).filter(
            (child) => child.getAttribute('aria-hidden') !== 'true'
        );
        expect(readerVisible.map((child) => child.textContent)).toEqual(['user_id']);
        expect(descriptionOf('row')).toBe('Restore changes this field. Current canvas: variables.user');
    });

    it('leaves a field the diff does not change unmarked', () => {
        render([onDiff('changed')]);

        expect(isMarked('libraries')).toBe(false);
        expect(element('libraries').hasAttribute('tabindex')).toBe(false);
        expect(element('libraries').hasAttribute('role')).toBe(false);
        expect(element('libraries').textContent?.trim()).toBe('Libraries');
    });

    it.each(['added', 'deleted'] as const)('marks nothing on a node whose status is %s', (status) => {
        render([onDiff(status)]);

        expect(isMarked('output-path')).toBe(false);
    });

    it('marks nothing without a diff: the Preview tab and the live editor', () => {
        render([]);

        expect(isMarked('output-path')).toBe(false);
        expect(element('output-path').hasAttribute('aria-describedby')).toBe(false);
    });

    it('shows the current canvas value on hover, the part a restore replaces struck, and hides it on leave', () => {
        render([onDiff('changed')]);

        dispatch('output-path', 'mouseenter');
        expect(tooltip()?.querySelector('.diff-field-mark__tooltip-label')?.textContent).toBe('Current canvas');
        expect(tooltipValue()).toBe('variables.[previous_]name');

        dispatch('output-path', 'mouseleave');
        expect(tooltip()).toBeNull();
    });

    it('shows the tooltip on keyboard focus and hides it on blur', () => {
        render([onDiff('changed')]);

        dispatch('output-path', 'focus');
        expect(tooltip()).not.toBeNull();

        dispatch('output-path', 'blur');
        expect(tooltip()).toBeNull();
    });

    it('hides the tooltip on Esc without letting Esc close the panel too', () => {
        render([onDiff('changed')]);
        const reachedPanel = vi.fn();
        fixture.nativeElement.addEventListener('keydown', reachedPanel);
        dispatch('output-path', 'focus');

        element('output-path').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        fixture.detectChanges();

        expect(tooltip()).toBeNull();
        expect(reachedPanel).not.toHaveBeenCalled();
    });

    it('hides a tooltip opened by hover on Esc anywhere, without letting Esc close the panel too', () => {
        render([onDiff('changed')]);
        const reachedPanel = vi.fn();
        window.addEventListener('keydown', reachedPanel);
        dispatch('output-path', 'mouseenter');

        document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        fixture.detectChanges();
        window.removeEventListener('keydown', reachedPanel);

        expect(tooltip()).toBeNull();
        expect(reachedPanel).not.toHaveBeenCalled();
    });

    it('lets Esc through once the tooltip is closed, so it still closes the panel', () => {
        render([onDiff('changed')]);
        const reachedPanel = vi.fn();
        fixture.nativeElement.addEventListener('keydown', reachedPanel);

        element('output-path').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

        expect(reachedPanel).toHaveBeenCalled();
    });

    it('opens no tooltip on an unmarked field', () => {
        render([onDiff('changed')]);

        dispatch('libraries', 'mouseenter');

        expect(tooltip()).toBeNull();
    });

    it('marks an element with the change it is given, e.g. one row of a map', () => {
        render([onDiff('changed', [])], { current: 'variables.user', version: 'variables.account' });

        expect(isMarked('row')).toBe(true);
        dispatch('row', 'mouseenter');
        expect(tooltipValue()).toBe('variables.[user]');
    });

    it('cuts a long current value in the description too, as in the tooltip', () => {
        render([onDiff('changed', [])], { current: `${'x'.repeat(100)}${'z'.repeat(100)}`, version: 'other' });

        expect(descriptionOf('row')).toBe(
            `Restore changes this field. Current canvas: ${'x'.repeat(50)}…${'z'.repeat(50)}`
        );
    });

    it('renders a stored value as text, never as markup', () => {
        render([onDiff('changed', [])], { current: '<img src=x onerror=alert(1)>', version: 'variables.x' });

        dispatch('row', 'mouseenter');

        expect(tooltipValue()).toBe('[<img src=x onerror=alert(1)>]');
        expect(tooltip()!.querySelector('img')).toBeNull();
    });
});
