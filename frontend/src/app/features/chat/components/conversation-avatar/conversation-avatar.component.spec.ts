import { ComponentFixture, TestBed } from '@angular/core/testing';

import { avatarColor } from '../../utils/desk-avatar.util';
import { ConversationAvatarComponent } from './conversation-avatar.component';

describe('ConversationAvatarComponent', () => {
    let fixture: ComponentFixture<ConversationAvatarComponent>;

    function render(visitorNumber: number, chatUserId: string | null): HTMLElement {
        fixture = TestBed.createComponent(ConversationAvatarComponent);
        fixture.componentRef.setInput('conversation', {
            id: 'c-42',
            visitor_number: visitorNumber,
            chat_user_id: chatUserId,
        });
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    it('shows the visitor number on the fill picked by the conversation id, hidden from assistive technology', () => {
        const host = render(12, null);
        expect(host.textContent?.trim()).toBe('12');
        expect(host.style.backgroundColor).toBe(avatarColor('c-42'));
        expect(host.getAttribute('aria-hidden')).toBe('true');
    });

    it("shows a signed visitor's initials instead", () => {
        expect(render(12, 'jane doe').textContent?.trim()).toBe('JD');
    });
});
