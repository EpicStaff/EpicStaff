import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ActivateButtonComponent } from './activate-button.component';

describe('ActivateButtonComponent', () => {
    let fixture: ComponentFixture<ActivateButtonComponent>;

    beforeEach(() => {
        fixture = TestBed.createComponent(ActivateButtonComponent);
        fixture.componentRef.setInput('tooltip', 'Resume binding');
        fixture.detectChanges();
    });

    it('names the icon-only button after its tooltip', () => {
        const button: HTMLButtonElement = fixture.nativeElement.querySelector('button');
        expect(button.getAttribute('aria-label')).toBe('Resume binding');
    });
});
