import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConversationSectionHeaderComponent } from './conversation-section-header.component';

describe('ConversationSectionHeaderComponent', () => {
    let fixture: ComponentFixture<ConversationSectionHeaderComponent>;

    function render(inputs: Record<string, unknown>): HTMLElement {
        fixture = TestBed.createComponent(ConversationSectionHeaderComponent);
        fixture.componentRef.setInput('label', 'Waiting for a person');
        fixture.componentRef.setInput('icon', 'user');
        fixture.componentRef.setInput('controlsId', 'section-body');
        Object.entries(inputs).forEach(([key, value]) => fixture.componentRef.setInput(key, value));
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    it('is a level-3 heading whose button says whether it is open and what it controls', () => {
        const host = render({ isExpanded: true });
        expect(host.getAttribute('role')).toBe('heading');
        expect(host.getAttribute('aria-level')).toBe('3');
        const button = host.querySelector('button')!;
        expect(button.getAttribute('aria-expanded')).toBe('true');
        expect(button.getAttribute('aria-controls')).toBe('section-body');
        expect(button.textContent?.trim()).toBe('Waiting for a person');

        render({ isExpanded: false });
        expect(fixture.nativeElement.querySelector('button').getAttribute('aria-expanded')).toBe('false');
    });

    it('asks to toggle on click', () => {
        const host = render({ isExpanded: true });
        const toggled = vi.fn();
        fixture.componentInstance.toggled.subscribe(toggled);
        host.querySelector('button')!.click();
        expect(toggled).toHaveBeenCalledTimes(1);
    });

    it('shows a count only when one is given', () => {
        expect(render({ isExpanded: true }).querySelector('.conversation-section-header__count')).toBeNull();
        expect(
            render({ isExpanded: true, count: 3 }).querySelector('.conversation-section-header__count')?.textContent
        ).toBe('3');
    });

    it('takes the focus without a jump, then comes into view', () => {
        const button = render({ isExpanded: true }).querySelector('button')!;
        const focus = vi.spyOn(button, 'focus');
        button.scrollIntoView = vi.fn();
        fixture.componentInstance.focus();
        expect(focus).toHaveBeenCalledWith({ preventScroll: true });
        expect(document.activeElement).toBe(button);
        expect(button.scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' });
    });
});
