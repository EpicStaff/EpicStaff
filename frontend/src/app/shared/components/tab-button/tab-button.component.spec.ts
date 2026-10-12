import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TabButtonComponent } from './tab-button.component';

describe('TabButtonComponent', () => {
    let fixture: ComponentFixture<TabButtonComponent>;

    const button = (): HTMLButtonElement => fixture.nativeElement.querySelector('button');

    beforeEach(() => {
        fixture = TestBed.createComponent(TabButtonComponent);
        fixture.detectChanges();
    });

    it('announces whether it is the active tab', () => {
        expect(button().getAttribute('aria-pressed')).toBe('false');

        fixture.componentRef.setInput('active', true);
        fixture.detectChanges();

        expect(button().getAttribute('aria-pressed')).toBe('true');
    });

    it('points its button at a description when given one', () => {
        expect(button().hasAttribute('aria-describedby')).toBe(false);

        fixture.componentRef.setInput('describedBy', 'why-disabled');
        fixture.detectChanges();

        expect(button().getAttribute('aria-describedby')).toBe('why-disabled');
    });
});
