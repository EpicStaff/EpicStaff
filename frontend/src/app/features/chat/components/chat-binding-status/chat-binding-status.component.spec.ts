import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ChatBinding } from '../../models/chat.model';
import { ChatBindingStatusComponent } from './chat-binding-status.component';

describe('ChatBindingStatusComponent', () => {
    let fixture: ComponentFixture<ChatBindingStatusComponent>;

    const pill = (): HTMLElement => fixture.nativeElement.querySelector('.binding-status');

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
        expect(pill().className).toBe('binding-status binding-status--live');
        show({ is_active: false });
        expect(pill().textContent?.trim()).toBe('Paused');
        expect(pill().className).toContain('binding-status--paused');
        show({ broken_reason: 'The flow was deleted.' });
        expect(pill().textContent?.trim()).toBe('Broken');
        expect(pill().className).toContain('binding-status--broken');
    });
});
