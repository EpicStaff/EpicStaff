import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ChatBinding } from '../../models/chat.model';
import { ChatBindingStatusComponent } from './chat-binding-status.component';

describe('ChatBindingStatusComponent', () => {
    let fixture: ComponentFixture<ChatBindingStatusComponent>;

    const pill = (): HTMLElement => fixture.nativeElement.querySelector('.binding-status');
    // What a screen reader announces after the label, from the elements `aria-describedby` points at.
    const description = (): string | null => {
        const ids = pill().getAttribute('aria-describedby');
        return ids
            ? ids
                  .split(' ')
                  .map((id) => document.getElementById(id)?.textContent ?? '')
                  .join(' ')
            : null;
    };

    function show(overrides: Partial<ChatBinding>): void {
        fixture.componentRef.setInput('binding', { is_active: true, broken_reason: null, ...overrides } as ChatBinding);
        fixture.detectChanges();
    }

    beforeEach(() => {
        fixture = TestBed.createComponent(ChatBindingStatusComponent);
    });

    it('labels each status and gives it the matching status-chip look, with no typography class of its own', () => {
        show({});
        expect(pill().textContent?.trim()).toBe('Live');
        const ownClasses = Array.from(pill().classList).filter((name) => !name.startsWith('mat-'));
        expect(ownClasses).toEqual(['binding-status', 'binding-status--live']);
        show({ is_active: false });
        expect(pill().textContent?.trim()).toBe('Paused');
        expect(pill().className).toContain('binding-status--paused');
        show({ broken_reason: 'The flow was deleted.' });
        expect(pill().textContent?.trim()).toBe('Broken');
        expect(pill().className).toContain('binding-status--broken');
    });

    it('tells why a broken binding is broken: focusable, described to assistive technology, shown on hover', async () => {
        show({});
        await fixture.whenStable();
        expect(pill().getAttribute('tabindex')).toBeNull();
        expect(description()).toBeNull();

        show({ broken_reason: 'The flow was deleted.' });
        await fixture.whenStable();
        expect(pill().getAttribute('tabindex')).toBe('0');
        expect(description()).toBe('The flow was deleted.');

        pill().dispatchEvent(new MouseEvent('mouseenter'));
        fixture.detectChanges();
        await fixture.whenStable();
        expect(document.querySelector('.mat-mdc-tooltip')?.textContent?.trim()).toBe('The flow was deleted.');
    });
});
