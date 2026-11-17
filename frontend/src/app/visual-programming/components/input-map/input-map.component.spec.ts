import { NgTemplateOutlet } from '@angular/common';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import {
    ChangeDetectorRef,
    Component,
    CUSTOM_ELEMENTS_SCHEMA,
    getDebugNode,
    NO_ERRORS_SCHEMA,
    signal,
} from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { GraphSessionService } from '../../../features/flows/services/flows-sessions.service';
import { RunSessionSSEService } from '../../../pages/running-graph/services/graph-session-sse.service';
import { ConfigService } from '../../../services/config';
import { FlowService } from '../../services/flow.service';
import { PythonCodeRunService } from '../../services/python-code-run.service';
import { SidePanelService } from '../../services/side-panel.service';
import { MapKeyChange } from '../../utils/diff';
import { DiffFieldMarkComponent } from '../diff-field-mark/diff-field-mark.component';
import { layOutWindowWithRowAt } from '../diff-field-mark/diff-mark-tooltip.testing';
import { provideChangesTabDiff } from '../missing-reference-note/missing-reference-note.testing';
import { InputMapComponent } from './input-map.component';

// The start node state a developer reported the picker order with.
const STATE = { variables: { my_object: { user_id: 'asdasdasdadadsa', user_email: 'test@mail.com' } } };

// The Python node panel's side of it: the form that holds the Input List.
@Component({
    imports: [ReactiveFormsModule, InputMapComponent],
    template: `<form [formGroup]="form"><app-input-map /></form>`,
})
class PythonPanelHostComponent {
    readonly form: FormGroup = new FormBuilder().group({
        input_map: new FormArray([new FormBuilder().group({ key: ['user'], value: ['variables.'] })]),
        test_input: new FormArray([]),
    });
}

describe('InputMapComponent variable picker', () => {
    let fixture: ComponentFixture<PythonPanelHostComponent>;

    const valueInput = (): HTMLInputElement => fixture.nativeElement.querySelector('.value-field-wrapper input');
    // Each row's full variable path, shown in its tooltip.
    const fullPath = (item: HTMLElement): string => getDebugNode(item)!.injector.get(MatTooltip).message;
    const listed = (): string[] =>
        Array.from(document.querySelectorAll<HTMLElement>('app-var-picker-flat .vpf-item'), fullPath);
    const typeValue = (text: string): void => {
        valueInput().value = text;
        valueInput().dispatchEvent(new Event('input'));
        fixture.detectChanges();
    };

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowService, useValue: { startNodeInitialState: signal(STATE) } },
                { provide: PythonCodeRunService, useValue: {} },
                { provide: GraphSessionService, useValue: {} },
                { provide: RunSessionSSEService, useValue: { status: signal(null) } },
                { provide: SidePanelService, useValue: {} },
            ],
        });
        // Only the rows matter here, not the header's tooltip and toggle.
        TestBed.overrideComponent(InputMapComponent, {
            set: { imports: [ReactiveFormsModule], schemas: [CUSTOM_ELEMENTS_SCHEMA] },
        });
        fixture = TestBed.createComponent(PythonPanelHostComponent);
        fixture.detectChanges();
    });

    afterEach(() => fixture.destroy());

    it('shows only top-level on focus, scopes into children on separator, and filters by what follows', () => {
        valueInput().dispatchEvent(new FocusEvent('focus'));
        fixture.detectChanges();
        expect(listed()).toEqual(['variables.my_object']);

        typeValue('.my');
        expect(listed()).toEqual(['variables.my_object']);

        typeValue('.my_object.');
        expect(listed()).toEqual(['variables.my_object.user_id', 'variables.my_object.user_email']);

        typeValue('.my_object.user_e');
        expect(listed()).toEqual(['variables.my_object.user_email']);
    });

    describe('with another row using the object', () => {
        const valueInputs = (): HTMLInputElement[] =>
            Array.from(fixture.nativeElement.querySelectorAll('.value-field-wrapper input'));
        const pairs = (): FormArray => fixture.componentInstance.form.get('input_map') as FormArray;
        const press = (key: string, init: KeyboardEventInit = {}): void => {
            valueInputs()[1].dispatchEvent(
                new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init })
            );
            fixture.detectChanges();
        };

        beforeEach(() => {
            pairs().insert(0, new FormBuilder().group({ key: ['whole'], value: ['variables.my_object'] }));
            // The OnPush host does not see the form change by itself.
            fixture.debugElement.injector.get(ChangeDetectorRef).markForCheck();
            fixture.detectChanges();
            valueInputs()[1].dispatchEvent(new FocusEvent('focus'));
            fixture.detectChanges();
        });

        afterEach(() => delete (Element.prototype as Partial<Element>).scrollIntoView);

        it('shows only the top-level object (disabled) on focus; children appear once scoped into', () => {
            expect(listed()).toEqual(['variables.my_object']);
            expect(Array.from(document.querySelectorAll<HTMLElement>('.vpf-item:disabled'), fullPath)).toEqual([
                'variables.my_object',
            ]);
            expect(valueInputs()[1].getAttribute('aria-expanded')).toBe('true');
        });

        it('adds a row on Enter on the untouched variables. prefill, as before', () => {
            press('Enter');

            expect(pairs().length).toBe(3);
            expect(pairs().at(1).value.value).toBe('variables.');
            expect(listed()).toEqual([]);
        });

        it('picks the first child on Enter once scoped into the object', () => {
            valueInputs()[1].value = '.my_object.';
            valueInputs()[1].dispatchEvent(new Event('input'));
            fixture.detectChanges();

            press('Enter');

            expect(pairs().at(1).value.value).toBe('variables.my_object.user_id');
            expect(pairs().length).toBe(2);
            expect(listed()).toEqual([]);
            expect(valueInputs()[1].getAttribute('aria-expanded')).toBe('false');
        });

        it('picks another field with the arrow keys and Enter once scoped into the object', () => {
            Element.prototype.scrollIntoView = vi.fn();

            // Scope into the object to see its children.
            valueInputs()[1].value = '.my_object.';
            valueInputs()[1].dispatchEvent(new Event('input'));
            fixture.detectChanges();

            // The first child (user_id) is preselected; ArrowDown moves to user_email.
            press('ArrowDown');
            press('Enter');

            expect(pairs().at(1).value.value).toBe('variables.my_object.user_email');
            expect(pairs().length).toBe(2);
        });

        it('still adds a row on Enter while the list has nothing to pick', () => {
            valueInputs()[1].value = '.nothing';
            valueInputs()[1].dispatchEvent(new Event('input'));
            fixture.detectChanges();

            press('Enter');

            expect(pairs().length).toBe(3);
            expect(pairs().at(1).value.value).toBe('variables.nothing');
            expect(listed()).toEqual([]);
        });

        it('adds a row on Enter once the pointer has left the list, not the row it passed over', () => {
            // On focus only the disabled top-level object shows; the pointer passes over it and leaves.
            document.querySelectorAll('.vpf-item')[0].dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
            document.querySelector('.vpf-list')!.dispatchEvent(new MouseEvent('mouseleave'));
            fixture.detectChanges();

            press('Enter');

            expect(pairs().length).toBe(3);
            expect(pairs().at(1).value.value).toBe('variables.');
        });

        it('adds no row on Enter with a modifier key, as before', () => {
            press('Enter', { shiftKey: true });

            expect(pairs().length).toBe(2);
            expect(listed().length).toBe(1);
        });
    });
});

// The Python node panel in Test mode, with a saved node whose Run the panel may block.
@Component({
    imports: [ReactiveFormsModule, InputMapComponent],
    template: `<form [formGroup]="form">
        <app-input-map
            [testMode]="true"
            [showTestMode]="true"
            [pythonNodeId]="31"
            [runTestBlocker]="blocker()"
            (runTest)="runs.push($event)"
        />
    </form>`,
})
class PythonPanelTestModeHostComponent {
    readonly form: FormGroup = new FormBuilder().group({
        input_map: new FormArray([new FormBuilder().group({ key: ['count'], value: ['variables.count'] })]),
        test_input: new FormArray([new FormBuilder().group({ key: ['count'], value: ['3'] })]),
    });
    readonly blocker = signal<string | null>(null);
    readonly runs: Record<string, string>[] = [];
}

describe('InputMapComponent test Run', () => {
    let fixture: ComponentFixture<PythonPanelTestModeHostComponent>;

    const runButton = (): HTMLButtonElement =>
        Array.from(
            (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('.test-mode-actions button')
        ).find((button) => button.textContent?.trim() === 'Run Test')!;
    const inputMap = (): InputMapComponent =>
        fixture.debugElement.query(By.directive(InputMapComponent)).componentInstance as InputMapComponent;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowService, useValue: { startNodeInitialState: signal({}) } },
                { provide: PythonCodeRunService, useValue: {} },
                { provide: GraphSessionService, useValue: {} },
                { provide: RunSessionSSEService, useValue: { status: signal(null) } },
                { provide: SidePanelService, useValue: {} },
            ],
        });
        // The buttons' tooltips are not rendered here: the tooltip text is read from the component.
        TestBed.overrideComponent(InputMapComponent, {
            set: { imports: [ReactiveFormsModule], schemas: [NO_ERRORS_SCHEMA] },
        });
        fixture = TestBed.createComponent(PythonPanelTestModeHostComponent);
        fixture.detectChanges();
    });

    afterEach(() => fixture.destroy());

    it('runs with the test values while the panel does not block it', () => {
        expect(runButton().disabled).toBe(false);

        runButton().click();

        expect(fixture.componentInstance.runs).toEqual([{ count: '3' }]);
    });

    it('is disabled, says why, and does not run while the panel blocks it', () => {
        fixture.componentInstance.blocker.set('Click Save to run your latest code changes');
        fixture.detectChanges();

        expect(runButton().disabled).toBe(true);
        expect(inputMap().getRunTestButtonTooltip()).toBe('Click Save to run your latest code changes');

        inputMap().onRunTest();
        expect(fixture.componentInstance.runs).toEqual([]);
    });
});

// The Python node panel of a saved node, which looks up the node's last successful session by the node's run name.
@Component({
    imports: [ReactiveFormsModule, InputMapComponent],
    template: `<form [formGroup]="form">
        <app-input-map
            [graphId]="7"
            [pythonNodeId]="42"
            [nodeName]="'Py'"
            [nodeNumber]="nodeNumber()"
        />
    </form>`,
})
class SavedPythonNodePanelHostComponent {
    readonly form: FormGroup = new FormBuilder().group({
        input_map: new FormArray([new FormBuilder().group({ key: ['count'], value: ['variables.count'] })]),
        test_input: new FormArray([]),
    });
    readonly nodeNumber = signal<number | undefined>(undefined);
}

describe('InputMapComponent last successful session lookup', () => {
    let fixture: ComponentFixture<SavedPythonNodePanelHostComponent>;
    let http: HttpTestingController;

    const searchedNodeNames = (): (string | null)[] =>
        http
            .match((request) => request.url === '/api/sessions/')
            .map((request) => request.request.params.get('node_name'));

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                { provide: FlowService, useValue: { startNodeInitialState: signal({}) } },
                { provide: PythonCodeRunService, useValue: {} },
                { provide: RunSessionSSEService, useValue: { status: signal(null) } },
                { provide: SidePanelService, useValue: {} },
            ],
        });
        TestBed.overrideComponent(InputMapComponent, {
            set: { imports: [ReactiveFormsModule], schemas: [NO_ERRORS_SCHEMA] },
        });
        http = TestBed.inject(HttpTestingController);
        fixture = TestBed.createComponent(SavedPythonNodePanelHostComponent);
    });

    afterEach(() => fixture.destroy());

    it.each([
        { nodeNumber: 3, runName: 'Py #3 #42' },
        { nodeNumber: undefined, runName: 'Py #42' },
    ])('searches sessions by $runName when the node number is $nodeNumber', ({ nodeNumber, runName }) => {
        fixture.componentInstance.nodeNumber.set(nodeNumber);
        fixture.detectChanges();

        expect(searchedNodeNames()).toEqual([runName]);
    });

    it('searches again under the new run name when the node gets a number', () => {
        fixture.detectChanges();
        const searchedBeforeTheNumber = searchedNodeNames();
        expect(searchedBeforeTheNumber).toEqual(['Py #42']);

        fixture.componentInstance.nodeNumber.set(2);
        fixture.detectChanges();

        expect(searchedNodeNames()).toEqual(['Py #2 #42']);
    });
});

// A read-only Input List showing a version (the version preview), with what a restore does to each row.
@Component({
    imports: [ReactiveFormsModule, InputMapComponent],
    template: `<form [formGroup]="form">
        <app-input-map
            [readonly]="true"
            [rowChanges]="rowChanges()"
        />
    </form>`,
})
class VersionInputListHostComponent {
    readonly rowChanges = signal<MapKeyChange[] | null>(null);
    readonly form: FormGroup = new FormBuilder().group({
        input_map: inputListOf([
            ['user', 'variables.account'],
            ['fresh', 'variables.fresh'],
            ['kept', 'variables.kept'],
        ]),
        test_input: new FormArray([]),
    });
}

function inputListOf(rows: [key: string, value: string][]): FormArray {
    return new FormArray(rows.map(([key, value]) => new FormBuilder().group({ key: [key], value: [value] })));
}

describe('InputMapComponent rows on the Changes tab of a version preview', () => {
    let fixture: ComponentFixture<VersionInputListHostComponent>;

    const RESTORE: MapKeyChange[] = [
        { key: 'fresh', status: 'added', current: null, version: 'variables.fresh' },
        { key: 'user', status: 'changed', current: 'variables.user', version: 'variables.account' },
        { key: 'gone', status: 'deleted', current: 'variables.gone', version: null },
    ];

    const ROW_MARKS: [className: string, mark: string][] = [
        ['diff-field-mark--shown', ' (changed)'],
        ['readonly-row--added', ' (added)'],
        ['readonly-row--removed', ' (removed)'],
    ];

    /** Each row as the user reads it, with its diff mark: `changed` / `added` / `removed`, or none. */
    const rows = (): string[] =>
        Array.from((fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('.readonly-row'), (row) => {
            const cells = Array.from(row.querySelectorAll('.readonly-cell'), (cell) =>
                cell.textContent?.replace(/\s+/g, ' ').trim()
            );
            const mark = ROW_MARKS.find(([className]) => row.classList.contains(className))?.[1] ?? '';
            return `${cells.join(' = ')}${mark}`;
        });

    /** `versionRows`: the rows the version has, in place of the default three. */
    function render(rowChanges: MapKeyChange[] | null, versionRows?: [key: string, value: string][]): void {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowService, useValue: { startNodeInitialState: signal(null) } },
                { provide: PythonCodeRunService, useValue: {} },
                { provide: GraphSessionService, useValue: {} },
                { provide: RunSessionSSEService, useValue: { status: signal(null) } },
                { provide: SidePanelService, useValue: {} },
                provideChangesTabDiff(),
            ],
        });
        TestBed.overrideComponent(InputMapComponent, {
            set: {
                imports: [ReactiveFormsModule, NgTemplateOutlet, DiffFieldMarkComponent, MatTooltip],
                schemas: [CUSTOM_ELEMENTS_SCHEMA],
            },
        });
        fixture = TestBed.createComponent(VersionInputListHostComponent);
        if (versionRows) fixture.componentInstance.form.setControl('input_map', inputListOf(versionRows));
        fixture.componentInstance.rowChanges.set(rowChanges);
        fixture.detectChanges();
    }

    afterEach(() => fixture.destroy());

    it('marks each row with what a restore does to it, and lists the rows a restore removes last', () => {
        render(RESTORE);

        expect(rows()).toEqual([
            'user = variables.account (changed)',
            'Restore adds this input: fresh = variables.fresh (added)',
            'kept = variables.kept',
            'Restore removes this input: gone = variables.gone (removed)',
        ]);
    });

    it('shows only the rows a restore removes when the version has none (no blank row above them)', () => {
        // A panel's form holds one blank pair when the node has no input list.
        render([{ key: 'gone', status: 'deleted', current: 'variables.gone', version: null }], [['', '']]);

        expect(rows()).toEqual(['Restore removes this input: gone = variables.gone (removed)']);
    });

    it('shows the current value of a changed row on hover; the other rows have no tooltip', () => {
        render(RESTORE);
        const [changed, added, , removed] = Array.from(
            (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('.readonly-row')
        );

        for (const row of [added, removed]) row.dispatchEvent(new Event('mouseenter'));
        fixture.detectChanges();
        expect(document.querySelector('.diff-field-mark__tooltip')).toBeNull();
        // Their status is read out instead (see above); a native tooltip would cover the cells' own.
        expect([added, removed].map((row) => row.hasAttribute('title'))).toEqual([false, false]);

        changed.dispatchEvent(new Event('mouseenter'));
        fixture.detectChanges();
        expect(document.querySelector('.diff-field-mark__tooltip-value')?.textContent?.replace(/\s/g, '')).toBe(
            'variables.user'
        );
    });

    describe('the cell tooltips next to the diff tooltip of a changed row', () => {
        afterEach(() => vi.restoreAllMocks());

        const readonlyRows = (): HTMLElement[] =>
            Array.from((fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('.readonly-row'));

        /**
         * Points at the row, as a user does before a cell's own tooltip opens (after its delay), and gives the side
         * each cell asks its tooltip to open on. jsdom cannot lay out where Material then puts it.
         */
        async function cellTooltipSides(row: HTMLElement): Promise<string[]> {
            row.dispatchEvent(new Event('mouseenter'));
            fixture.detectChanges();
            // The diff tooltip is placed once it has rendered and reports its side; the next check applies it.
            await fixture.whenStable();
            fixture.detectChanges();
            return Array.from(
                row.querySelectorAll<HTMLElement>('.readonly-cell'),
                (cell) => getDebugNode(cell)!.injector.get(MatTooltip).position
            );
        }

        it.each([
            // Room above the row: the diff tooltip opens above it.
            { where: 'above', rowTop: 300, cells: ['below', 'below'] },
            // No room above the row (window top): the diff tooltip opens below it.
            { where: 'below', rowTop: 4, cells: ['above', 'above'] },
        ])('opens them on the other side of the row when the diff tooltip is $where it', async ({ rowTop, cells }) => {
            render(RESTORE);
            const [changed] = readonlyRows();
            layOutWindowWithRowAt(changed, rowTop);

            expect(await cellTooltipSides(changed)).toEqual(cells);
            expect(document.querySelector('.diff-field-mark__tooltip')).not.toBeNull();
        });

        it.each([
            { row: 'a row a restore keeps', rowChanges: RESTORE, rowIndex: 2 },
            { row: 'any row without row changes (the live editor)', rowChanges: null, rowIndex: 0 },
        ])('keeps them above on $row', async ({ rowChanges, rowIndex }) => {
            render(rowChanges);
            const row = readonlyRows()[rowIndex];
            layOutWindowWithRowAt(row, 4);

            expect(await cellTooltipSides(row)).toEqual(['above', 'above']);
        });
    });

    it('shows the rows as they are without row changes, as everywhere but the Changes tab', () => {
        render(null);

        expect(rows()).toEqual(['user = variables.account', 'fresh = variables.fresh', 'kept = variables.kept']);
    });
});

@Component({
    imports: [ReactiveFormsModule, InputMapComponent],
    template: `<form [formGroup]="form">
        <app-input-map
            [label]="label()"
            [keyPlaceholder]="keyPlaceholder()"
            [valuePlaceholder]="valuePlaceholder()"
        />
    </form>`,
})
class CopyHostComponent {
    readonly label = signal('');
    readonly keyPlaceholder = signal('');
    readonly valuePlaceholder = signal('');
    readonly form: FormGroup = new FormBuilder().group({
        input_map: new FormArray([new FormBuilder().group({ key: [''], value: [''] })]),
        test_input: new FormArray([]),
    });
}

describe('InputMapComponent copy', () => {
    let fixture: ComponentFixture<PythonPanelHostComponent | CopyHostComponent>;
    const text = (): string => fixture.nativeElement.textContent;
    const placeholders = (): string[] =>
        Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('input'), (input) => input.placeholder);

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowService, useValue: { startNodeInitialState: signal(STATE) } },
                { provide: PythonCodeRunService, useValue: {} },
                { provide: GraphSessionService, useValue: {} },
                { provide: RunSessionSSEService, useValue: { status: signal(null) } },
                { provide: SidePanelService, useValue: {} },
            ],
        });
        TestBed.overrideComponent(InputMapComponent, {
            set: { imports: [ReactiveFormsModule], schemas: [CUSTOM_ELEMENTS_SCHEMA] },
        });
    });

    afterEach(() => fixture.destroy());

    it('keeps the Input List header and placeholders for callers that set nothing', () => {
        fixture = TestBed.createComponent(PythonPanelHostComponent);
        fixture.detectChanges();

        expect(text()).toContain('Input List');
        expect(placeholders()).toEqual(['Function Argument Name', 'all fields']);
    });

    it('takes its own header and key placeholder, and shows no header for an empty label', () => {
        const host = TestBed.createComponent(CopyHostComponent);
        fixture = host;
        host.componentInstance.keyPlaceholder.set('Name');
        host.componentInstance.valuePlaceholder.set('Flow variable');
        host.detectChanges();

        expect(text()).not.toContain('Input List');
        expect(fixture.nativeElement.querySelector('.input-map-header')).toBeNull();
        expect(placeholders()).toEqual(['Name', 'all fields']);
    });
});

// A panel's form with a stored Input List: a named row without a path, a filled row and an empty row.
@Component({
    imports: [ReactiveFormsModule, InputMapComponent],
    template: `<form [formGroup]="form"><app-input-map /></form>`,
})
class StoredRowsHostComponent {
    readonly form: FormGroup = new FormBuilder().group({
        input_map: new FormArray([
            new FormBuilder().group({ key: ['topic'], value: [''] }),
            new FormBuilder().group({ key: ['user'], value: ['variables.user'] }),
            new FormBuilder().group({ key: [''], value: ['variables.'] }),
        ]),
        test_input: new FormArray([]),
    });
}

describe('InputMapComponent message on a named row without a variable path', () => {
    const MESSAGE = 'Choose a variable path, or remove this row.';
    let fixture: ComponentFixture<StoredRowsHostComponent>;

    const rows = (): HTMLElement[] => Array.from(fixture.nativeElement.querySelectorAll('.input-map-item'));
    const messages = (): (string | null)[] =>
        rows().map((row) => row.querySelector('.missing-path-message')?.textContent?.trim() ?? null);
    const keyInput = (row: number): HTMLInputElement => rows()[row].querySelector('input[formControlName="key"]')!;
    const valueInput = (row: number): HTMLInputElement => rows()[row].querySelector('.value-field-wrapper input')!;
    const type = (input: HTMLInputElement, text: string): void => {
        input.value = text;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    };

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowService, useValue: { startNodeInitialState: signal({}) } },
                { provide: PythonCodeRunService, useValue: {} },
                { provide: GraphSessionService, useValue: {} },
                { provide: RunSessionSSEService, useValue: { status: signal(null) } },
                { provide: SidePanelService, useValue: {} },
            ],
        });
        TestBed.overrideComponent(InputMapComponent, {
            set: { imports: [ReactiveFormsModule], schemas: [CUSTOM_ELEMENTS_SCHEMA] },
        });
        fixture = TestBed.createComponent(StoredRowsHostComponent);
        fixture.detectChanges();
    });

    afterEach(() => fixture.destroy());

    it('shows under a stored named row without a path, read with its path field, and under no other row', () => {
        expect(messages()).toEqual([MESSAGE, null, null]);
        const message = rows()[0].querySelector('.missing-path-message')!;
        expect(valueInput(0).getAttribute('aria-describedby')).toBe(message.id);
        expect(valueInput(1).hasAttribute('aria-describedby')).toBe(false);
    });

    it('goes once a path is typed, and stays gone when the path is cleared back to all fields', () => {
        type(valueInput(0), '.topic');
        expect(messages()[0]).toBeNull();

        type(valueInput(0), '');
        expect(messages()[0]).toBeNull();
    });

    it('stays while the author renames the row, and goes when the name is cleared', () => {
        type(keyInput(0), 'subject');
        expect(messages()[0]).toBe(MESSAGE);

        type(keyInput(0), '');
        expect(messages()[0]).toBeNull();
    });

    it('shows no message on a named row with the variables. path, which maps all fields', () => {
        type(keyInput(2), 'company');

        expect(messages()).toEqual([MESSAGE, null, null]);
    });
});
