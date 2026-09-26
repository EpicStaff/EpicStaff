import { ChangeDetectorRef, Component, CUSTOM_ELEMENTS_SCHEMA, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';

import { GraphSessionService } from '../../../features/flows/services/flows-sessions.service';
import { RunSessionSSEService } from '../../../pages/running-graph/services/graph-session-sse.service';
import { FlowService } from '../../services/flow.service';
import { PythonCodeRunService } from '../../services/python-code-run.service';
import { SidePanelService } from '../../services/side-panel.service';
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

    const valueInput = (): HTMLInputElement => fixture.nativeElement.querySelector('input[formControlName="value"]');
    const listed = (): string[] =>
        Array.from(document.querySelectorAll<HTMLElement>('app-var-picker-flat .vpf-item'), (item) => item.title);
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

    it('lists an object before its fields, and keeps it above the fields a filter matches', () => {
        valueInput().dispatchEvent(new FocusEvent('focus'));
        fixture.detectChanges();
        expect(listed()).toEqual([
            'variables.my_object',
            'variables.my_object.user_id',
            'variables.my_object.user_email',
        ]);

        typeValue('variables.user');
        expect(listed()).toEqual([
            'variables.my_object',
            'variables.my_object.user_id',
            'variables.my_object.user_email',
        ]);

        typeValue('variables.my_object.user_e');
        expect(listed()).toEqual(['variables.my_object', 'variables.my_object.user_email']);
    });

    describe('with another row using the object', () => {
        const valueInputs = (): HTMLInputElement[] =>
            Array.from(fixture.nativeElement.querySelectorAll('input[formControlName="value"]'));
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

        it('keeps the object above its fields, disabled, and offers the fields', () => {
            expect(listed()).toEqual([
                'variables.my_object',
                'variables.my_object.user_id',
                'variables.my_object.user_email',
            ]);
            expect(
                Array.from(document.querySelectorAll<HTMLElement>('.vpf-item:disabled'), (item) => item.title)
            ).toEqual(['variables.my_object']);
            expect(valueInputs()[1].getAttribute('aria-expanded')).toBe('true');
        });

        it('picks a field with the arrow keys and Enter, passing the object by', () => {
            Element.prototype.scrollIntoView = vi.fn();

            press('ArrowDown');
            press('Enter');

            expect(pairs().at(1).value.value).toBe('variables.my_object.user_id');
            expect(pairs().length).toBe(2);
            expect(listed()).toEqual([]);
            expect(valueInputs()[1].getAttribute('aria-expanded')).toBe('false');
        });

        it('still adds a row on Enter while nothing is highlighted', () => {
            press('Enter');

            expect(pairs().length).toBe(3);
            expect(pairs().at(1).value.value).toBe('variables.');
            expect(listed()).toEqual([]);
        });

        it('adds a row on Enter once the pointer has left the list, not the row it passed over', () => {
            document.querySelectorAll('.vpf-item')[2].dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
            document.querySelector('.vpf-list')!.dispatchEvent(new MouseEvent('mouseleave'));
            fixture.detectChanges();

            press('Enter');

            expect(pairs().length).toBe(3);
            expect(pairs().at(1).value.value).toBe('variables.');
        });

        it('adds no row on Enter with a modifier key, as before', () => {
            press('Enter', { shiftKey: true });

            expect(pairs().length).toBe(2);
            expect(listed().length).toBe(3);
        });
    });
});
