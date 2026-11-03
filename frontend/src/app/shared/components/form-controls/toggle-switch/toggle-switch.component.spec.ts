import { TestBed } from '@angular/core/testing';

import { ToggleSwitchComponent } from './toggle-switch.component';

describe('ToggleSwitchComponent', () => {
    function mount(options: { disabled?: boolean } = {}) {
        const fixture = TestBed.createComponent(ToggleSwitchComponent);
        fixture.componentRef.setInput('disabled', options.disabled ?? false);
        fixture.detectChanges();
        const changes: boolean[] = [];
        fixture.componentInstance.checkedChange.subscribe((checked) => changes.push(checked));
        const checkbox: HTMLInputElement = fixture.nativeElement.querySelector('input');
        return { fixture, changes, checkbox };
    }

    function pressEnter(element: HTMLElement): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true });
        element.dispatchEvent(event);
        return event;
    }

    it('flips on Enter, as on a click', () => {
        const { fixture, changes, checkbox } = mount();

        const enter = pressEnter(checkbox);
        fixture.detectChanges();
        pressEnter(checkbox);

        expect(changes).toEqual([true, false]);
        expect(enter.defaultPrevented).toBe(true);
    });

    it('stays as it is on Enter while disabled', () => {
        const { changes, checkbox } = mount({ disabled: true });

        pressEnter(checkbox);

        expect(changes).toEqual([]);
    });
});
