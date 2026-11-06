import { Component, EnvironmentProviders, input, NgZone, Provider, provideZoneChangeDetection } from '@angular/core';
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
            id="venv"
            [diffField]="'python_code.venv_id'"
        >
            <label>Venv</label>
        </app-diff-field-mark>
        <app-diff-field-mark
            id="code"
            [diffField]="'python_code.code'"
            [diffHint]="'Expand editor to see the changes.'"
            [diffDrawsBadge]="true"
        >
            <div class="code-editor"></div>
        </app-diff-field-mark>
        <div
            id="row"
            appDiffFieldMark
            [diffChange]="rowChange()"
        >
            <span>user_id</span>
        </div>
        <div
            id="help-row"
            appDiffFieldMark
            [diffChange]="rowChange()"
        >
            <span id="help-row-text">Question type</span>
            <span data-own-tooltip>
                <button
                    id="help-row-icon"
                    type="button"
                >
                    ?
                </button>
            </span>
        </div>
        <div
            id="table-row"
            role="row"
            appDiffFieldMark
            diffLabel="Restore changes this input"
            [diffChange]="rowChange()"
        >
            <span>user_id</span>
        </div>
        <app-diff-field-mark
            id="subflow"
            [diffField]="'subgraph'"
            [diffFormat]="flowName"
        >
            <span>Billing</span>
        </app-diff-field-mark>
        <app-diff-field-mark
            id="search-settings"
            [diffChange]="groupChange()"
            [diffGroup]="true"
        >
            <input value="3" />
            <input value="0.7" />
        </app-diff-field-mark>
    `,
})
class PanelFieldsComponent {
    readonly rowChange = input<DiffFieldMarkChange | null>(null);
    readonly groupChange = input<DiffFieldMarkChange | null>(null);
    readonly flowName = (id: unknown): string => (id === 41 ? 'Billing' : `flow #${String(id)}`);
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

function render(
    providers: (Provider | EnvironmentProviders)[],
    rowChange: DiffFieldMarkChange | null = null,
    groupChange: DiffFieldMarkChange | null = null
): void {
    TestBed.configureTestingModule({ providers });
    fixture = TestBed.createComponent(PanelFieldsComponent);
    fixture.componentRef.setInput('rowChange', rowChange);
    fixture.componentRef.setInput('groupChange', groupChange);
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
        expect(element('venv').classList).not.toContain('diff-value-marked');
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

    it("keeps a marked row's own role and names the row by its label, which its badge does not repeat", () => {
        render([onDiff('changed', [])], { current: 'variables.user', version: 'variables.account' });

        expect(element('table-row').getAttribute('role')).toBe('row');
        expect(descriptionOf('table-row')).toBe('Restore changes this input. Current canvas: variables.user');
        // The row's own tooltip opens over the badge too; a native one on the badge would be a second.
        const badge = element('table-row').querySelector('.diff-field-mark__badge')!;
        expect(badge.getAttribute('aria-hidden')).toBe('true');
        expect(badge.hasAttribute('title')).toBe(false);
    });

    it('leaves a field the diff does not change unmarked', () => {
        render([onDiff('changed')]);

        expect(isMarked('venv')).toBe(false);
        expect(element('venv').hasAttribute('tabindex')).toBe(false);
        expect(element('venv').hasAttribute('role')).toBe(false);
        expect(element('venv').textContent?.trim()).toBe('Venv');
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

    it('paints the tooltip with the tooltip tokens the rest of the app uses', () => {
        render([onDiff('changed')]);

        dispatch('output-path', 'mouseenter');
        const style = getComputedStyle(tooltip()!);

        expect({ background: style.backgroundColor, color: style.color, filter: style.filter }).toEqual({
            background: 'var(--tooltip-bg)',
            color: 'var(--tooltip-text)',
            filter: 'var(--tooltip-shadow)',
        });
    });

    describe('around an element with a tooltip of its own (a help icon)', () => {
        const ROW_CHANGE = { current: 'choice', version: 'score' };

        function pointAt(id: string): void {
            element(id).dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
            fixture.detectChanges();
        }

        it('shows only the help while the pointer is on it, and the diff tooltip elsewhere in the row', () => {
            render([onDiff('changed', [])], ROW_CHANGE);
            dispatch('help-row', 'mouseenter');
            pointAt('help-row-text');
            expect(tooltip()).not.toBeNull();

            pointAt('help-row-icon');
            expect(tooltip()).toBeNull();

            pointAt('help-row-text');
            expect(tooltip()).not.toBeNull();
        });

        /** Moves the focus onto the help icon with Tab, as a keyboard user does. */
        function tabOntoHelp(): void {
            element('help-row-icon').dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
            element('help-row-icon').dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
            fixture.detectChanges();
        }

        it('shows only the help while the keyboard focus is on it, though the pointer is on the row', () => {
            render([onDiff('changed', [])], ROW_CHANGE);
            dispatch('help-row', 'mouseenter');
            pointAt('help-row-text');

            tabOntoHelp();
            expect(tooltip()).toBeNull();

            element('help-row-icon').dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
            fixture.detectChanges();
            expect(tooltip()).not.toBeNull();
        });

        it('shows the diff tooltip again when the pointer leaves a help icon it clicked, though the icon keeps the focus', () => {
            render([onDiff('changed', [])], ROW_CHANGE);
            dispatch('help-row', 'mouseenter');
            pointAt('help-row-icon');
            element('help-row-icon').dispatchEvent(
                new MouseEvent('mousedown', { bubbles: true, buttons: 1, detail: 1 })
            );
            element('help-row-icon').dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
            fixture.detectChanges();
            expect(tooltip()).toBeNull();

            pointAt('help-row-text');

            expect(tooltip()).not.toBeNull();
        });

        it('lets Esc through to the panel while the diff tooltip is hidden for the help', () => {
            render([onDiff('changed', [])], ROW_CHANGE);
            dispatch('help-row', 'mouseenter');
            tabOntoHelp();
            const panelEscapes: KeyboardEvent[] = [];
            const onDocumentKeydown = (event: KeyboardEvent): void => {
                if (event.key === 'Escape') panelEscapes.push(event);
            };
            document.addEventListener('keydown', onDocumentKeydown);

            element('help-row-icon').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            document.removeEventListener('keydown', onDocumentKeydown);

            expect(panelEscapes).toHaveLength(1);
        });

        it('listens for own tooltips only on a shown mark, outside the zone; the live editor adds no listener', () => {
            const added: string[] = [];
            const addEventListener = EventTarget.prototype.addEventListener;
            vi.spyOn(EventTarget.prototype, 'addEventListener').mockImplementation(function (
                this: EventTarget,
                ...args: Parameters<EventTarget['addEventListener']>
            ) {
                const isMark = this instanceof HTMLElement && this.id === 'help-row';
                if (isMark && ['mouseover', 'focusin', 'focusout'].includes(args[0])) {
                    added.push(`${args[0]} ${NgZone.isInAngularZone() ? 'inside' : 'outside'} the zone`);
                }
                addEventListener.apply(this, args);
            });

            // The app runs change detection from zone.js, as `app.config.ts` sets it up.
            const zoned = provideZoneChangeDetection({ eventCoalescing: true });
            render([zoned], ROW_CHANGE);
            expect(added).toEqual([]);
            TestBed.resetTestingModule();

            render([zoned, onDiff('changed', [])], ROW_CHANGE);
            expect(added).toEqual(['mouseover', 'focusin', 'focusout'].map((type) => `${type} outside the zone`));
            vi.restoreAllMocks();
        });

        it('opens again on the next hover after the pointer left from the help', () => {
            render([onDiff('changed', [])], ROW_CHANGE);
            dispatch('help-row', 'mouseenter');
            pointAt('help-row-icon');
            dispatch('help-row', 'mouseleave');

            dispatch('help-row', 'mouseenter');

            expect(tooltip()).not.toBeNull();
        });
    });

    it('opens no tooltip on an unmarked field', () => {
        render([onDiff('changed')]);

        dispatch('venv', 'mouseenter');

        expect(tooltip()).toBeNull();
    });

    describe('on a code', () => {
        const CODE_CHANGE: FieldChange = {
            path: 'python_code.code',
            field: 'python_code.code',
            status: 'changed',
            current: 'def main():\n    return 1\n',
            version: 'def main():\n    return 2\n',
        };

        it('gives the hint instead of the code, on hover and to screen readers, and still names the change', () => {
            render([onDiff('changed', [CODE_CHANGE])]);
            dispatch('code', 'mouseenter');

            expect(tooltip()?.textContent?.trim()).toBe('Expand editor to see the changes.');
            expect(tooltip()?.querySelector('.diff-field-mark__tooltip-label')).toBeNull();
            expect(descriptionOf('code')).toBe('Expand editor to see the changes.');
            const name = document.getElementById(element('code').getAttribute('aria-labelledby')!);
            expect(name?.textContent).toBe('Restore changes this field');
        });

        // The code editor card clips what sticks out, so the mark carries the badge (and the focus ring) itself.
        it('asks the code editor to frame its value and draws the badge itself, only while the code is marked', () => {
            render([onDiff('changed', [CODE_CHANGE, OUTPUT_PATH_CHANGE])]);

            expect(element('code').classList).toContain('diff-value-marked');
            expect(element('code').classList).toContain('diff-field-mark--draws-badge');
            // A field that draws its own badge.
            expect(element('output-path').classList).not.toContain('diff-field-mark--draws-badge');
        });

        it.each([
            { case: 'the code is unchanged', providers: () => [onDiff('changed')] },
            { case: 'the node is added', providers: () => [onDiff('added', [CODE_CHANGE])] },
            { case: 'the node is removed', providers: () => [onDiff('deleted', [CODE_CHANGE])] },
            { case: 'off the Changes tab (Preview tab, live editor)', providers: () => [] },
        ])('marks nothing when $case', ({ providers }) => {
            render(providers());

            expect(isMarked('code')).toBe(false);
            expect(element('code').classList).not.toContain('diff-value-marked');
            expect(element('code').classList).not.toContain('diff-field-mark--draws-badge');
        });
    });

    it('shows a value the way the field shows it when given a display format, e.g. a linked flow by name', () => {
        const subflowChange: FieldChange = {
            path: 'subgraph',
            field: 'subgraph',
            status: 'changed',
            current: 41,
            version: 42,
        };
        render([onDiff('changed', [subflowChange])]);

        dispatch('subflow', 'mouseenter');

        expect(tooltipValue()).toBe('[Billing]');
        expect(descriptionOf('subflow')).toBe('Current canvas: Billing');
    });

    describe('around a group of inputs', () => {
        const SETTINGS_CHANGE: DiffFieldMarkChange = { current: { limit: 3 }, version: { limit: 5 } };

        it('boxes the group itself, and does not ask the inputs inside to mark their values', () => {
            render([onDiff('changed', [])], null, SETTINGS_CHANGE);

            expect(isMarked('search-settings')).toBe(true);
            expect(element('search-settings').classList).toContain('diff-field-mark--group');
            expect(element('search-settings').classList).not.toContain('diff-value-marked');
            expect(element('search-settings').getAttribute('role')).toBe('group');
            dispatch('search-settings', 'mouseenter');
            expect(tooltipValue()).toBe('{"limit":[3]}');
        });

        it.each([
            { case: 'without a change', providers: () => [onDiff('changed', [])], change: null },
            { case: 'on a node a restore removes', providers: () => [onDiff('deleted', [])], change: SETTINGS_CHANGE },
            { case: 'off the Changes tab', providers: () => [], change: SETTINGS_CHANGE },
        ])('leaves the group as it is $case', ({ providers, change }) => {
            render(providers(), null, change);

            expect(isMarked('search-settings')).toBe(false);
            expect(element('search-settings').classList).not.toContain('diff-field-mark--group');
        });
    });

    it('marks an element with the change it is given, e.g. one row of a map', () => {
        render([onDiff('changed', [])], { current: 'variables.user', version: 'variables.account' });

        expect(isMarked('row')).toBe(true);
        dispatch('row', 'mouseenter');
        expect(tooltipValue()).toBe('variables.[user]');
    });

    it('cuts a long current value in the description too, as in the tooltip', () => {
        const start = `${'s'.repeat(40)}${'m'.repeat(30)}${'c'.repeat(20)}`;
        render([onDiff('changed', [])], {
            current: `${start}${'x'.repeat(100)}${'z'.repeat(100)}${'d'.repeat(30)}`,
            version: `${start}Y${'d'.repeat(30)}`,
        });

        expect(descriptionOf('row')).toBe(
            `Restore changes this field. Current canvas: ${'s'.repeat(40)}…${'c'.repeat(20)}` +
                `${'x'.repeat(50)}…${'z'.repeat(50)}${'d'.repeat(20)}…`
        );
    });

    it('renders a stored value as text, never as markup', () => {
        render([onDiff('changed', [])], { current: '<img src=x onerror=alert(1)>', version: 'variables.x' });

        dispatch('row', 'mouseenter');

        expect(tooltipValue()).toBe('[<img src=x onerror=alert(1)>]');
        expect(tooltip()!.querySelector('img')).toBeNull();
    });
});
