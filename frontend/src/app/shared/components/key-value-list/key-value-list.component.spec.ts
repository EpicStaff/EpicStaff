import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { SecretsStorageService } from '@shared/services';
import { of } from 'rxjs';

import { KeyValueListComponent } from './key-value-list.component';

@Component({
    imports: [KeyValueListComponent, ReactiveFormsModule],
    template: `<app-key-value-list [formControl]="control" />`,
})
class HostComponent {
    readonly control = new FormControl<Record<string, string>>({});
}

describe('KeyValueListComponent', () => {
    function setup() {
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: SecretsStorageService,
                    useValue: { secrets: () => [], getSecrets: () => of([]) },
                },
            ],
        });
        const fixture = TestBed.createComponent(HostComponent);
        fixture.detectChanges();
        const list = fixture.debugElement.children[0].componentInstance as KeyValueListComponent;
        return { fixture, control: fixture.componentInstance.control, list };
    }

    it('is invalid when a saved row has a bad header name and valid once fixed', () => {
        const { fixture, control, list } = setup();
        control.setValue({ 'bad name': 'x' });
        fixture.detectChanges();
        expect(control.invalid).toBe(true);

        list.updateName(0, 'good-name');
        fixture.detectChanges();
        control.updateValueAndValidity();
        expect(control.valid).toBe(true);
    });

    it('revalidates when the draft is edited', () => {
        const { control, list } = setup();
        expect(control.valid).toBe(true);

        list.updateDraftName('X-Name');
        expect(control.invalid).toBe(true);
        expect(list.draftError()).toBe('Add or clear this header first');

        list.updateDraftName('');
        expect(control.valid).toBe(true);

        list.updateDraftValue('only-value');
        expect(control.invalid).toBe(true);
    });

    it('blocks validity for a draft that is confirmed away only after confirm', () => {
        const { control, list } = setup();
        list.updateDraftName('X-Name');
        expect(control.invalid).toBe(true);

        list.confirm();
        expect(control.valid).toBe(true);
        expect(control.value).toEqual({ 'X-Name': '' });
    });

    it('ignores an entirely empty row', () => {
        const { fixture, control } = setup();
        control.setValue({ '': '' });
        fixture.detectChanges();
        expect(control.valid).toBe(true);
    });
});
