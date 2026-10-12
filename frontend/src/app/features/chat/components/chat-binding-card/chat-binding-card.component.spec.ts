import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { CHAT_BINDING_DEFAULTS, ChatBinding } from '../../models/chat.model';
import { ChatBindingCardComponent } from './chat-binding-card.component';

const binding = (overrides: Partial<ChatBinding> = {}): ChatBinding => ({
    ...CHAT_BINDING_DEFAULTS,
    id: 'b-1',
    org_id: 1,
    graph_id: 5,
    name: 'Support',
    bot_display_name: 'Support',
    public_key: 'pk',
    is_active: true,
    token_budget_per_conversation: 1000,
    daily_token_budget: 1_000_000,
    broken_reason: null,
    contract_errors: [],
    created_at: '',
    updated_at: '',
    ...overrides,
});

describe('ChatBindingCardComponent', () => {
    let fixture: ComponentFixture<ChatBindingCardComponent>;

    const trigger = (): HTMLButtonElement => fixture.nativeElement.querySelector('.binding-card__menu-btn');
    const menuOpen = (): boolean => !!document.querySelector('.binding-card-menu');

    beforeEach(() => {
        TestBed.configureTestingModule({
            imports: [ChatBindingCardComponent],
            providers: [provideRouter([]), { provide: PermissionsService, useValue: { can: () => true } }],
        });
        fixture = TestBed.createComponent(ChatBindingCardComponent);
        fixture.componentRef.setInput('binding', binding());
        fixture.detectChanges();
    });

    afterEach(() => fixture.destroy());

    // CDK's connected overlay leaves clicks on its origin out of overlayOutsideClick, so the trigger's own toggle closes it.
    it('closes its menu from the trigger it was opened with, and from a click elsewhere', () => {
        trigger().click();
        fixture.detectChanges();
        expect(menuOpen()).toBe(true);
        expect(trigger().getAttribute('aria-expanded')).toBe('true');

        trigger().click();
        fixture.detectChanges();
        expect(menuOpen()).toBe(false);

        trigger().click();
        fixture.detectChanges();
        document.body.click();
        fixture.detectChanges();
        expect(menuOpen()).toBe(false);
    });

    it('lists its actions as plain buttons, not an arrow-key menu', () => {
        trigger().click();
        fixture.detectChanges();
        expect(document.querySelector('.binding-card-menu [role]')).toBeNull();
        expect(document.querySelector('.binding-card-menu')?.getAttribute('role')).toBeNull();
    });

    it('shows why a broken binding is broken as text on the card', () => {
        expect(fixture.nativeElement.querySelector('.binding-card__reason')).toBeNull();
        fixture.componentRef.setInput('binding', binding({ broken_reason: 'The flow was deleted.' }));
        fixture.detectChanges();
        expect(fixture.nativeElement.querySelector('.binding-card__reason')?.textContent?.trim()).toBe(
            'The flow was deleted.'
        );
    });
});
