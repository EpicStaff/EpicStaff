import { DialogRef } from '@angular/cdk/dialog';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';

import { ToggleSwitchComponent } from '../components/form-controls/toggle-switch/toggle-switch.component';
import { EnterSubmitDirective } from './enter-submit.directive';

@Component({
    imports: [EnterSubmitDirective, ToggleSwitchComponent],
    template: `
        <form (appEnterSubmit)="submits = submits + 1">
            <input
                class="name"
                type="text"
            />
            <app-toggle-switch
                [checked]="checked"
                (checkedChange)="checked = $event"
            />
        </form>
    `,
})
class DialogContentComponent {
    submits = 0;
    checked = false;
}

describe('EnterSubmitDirective', () => {
    // The dialog hands keys to its content after they have passed the focused element, as the CDK overlay does.
    const dialogKeys = new Subject<KeyboardEvent>();

    function pressEnter(target: HTMLElement): void {
        const event = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true });
        target.dispatchEvent(event);
        dialogKeys.next(event);
    }

    function mount() {
        TestBed.configureTestingModule({
            providers: [{ provide: DialogRef, useValue: { keydownEvents: dialogKeys } }],
        });
        const fixture = TestBed.createComponent(DialogContentComponent);
        fixture.detectChanges();
        return fixture;
    }

    it('submits on Enter in a text field', () => {
        const fixture = mount();

        pressEnter(fixture.nativeElement.querySelector('input.name'));

        expect(fixture.componentInstance.submits).toBe(1);
    });

    it('lets Enter on a toggle switch flip it without submitting', () => {
        const fixture = mount();

        pressEnter(fixture.nativeElement.querySelector('app-toggle-switch input'));

        expect(fixture.componentInstance.checked).toBe(true);
        expect(fixture.componentInstance.submits).toBe(0);
    });
});
