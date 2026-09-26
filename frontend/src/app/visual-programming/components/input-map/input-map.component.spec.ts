import { Component, CUSTOM_ELEMENTS_SCHEMA, signal } from '@angular/core';
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
});
