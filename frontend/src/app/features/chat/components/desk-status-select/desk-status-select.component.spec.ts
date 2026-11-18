import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { CHAT_BINDING_DEFAULTS, ChatBinding } from '../../models/chat.model';
import { DeskRunState, DeskStatusSelectComponent } from './desk-status-select.component';

const binding = (overrides: Partial<ChatBinding>): ChatBinding => ({
    ...CHAT_BINDING_DEFAULTS,
    response_time_seconds: 600,
    on_response_timeout: 'handback',
    handback_message: 'Back to the bot.',
    close_after_seconds: 86_400,
    id: 'b-1',
    org_id: 1,
    graph_id: 5,
    name: 'Sales',
    bot_display_name: 'Sales',
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

describe('DeskStatusSelectComponent', () => {
    let fixture: ComponentFixture<DeskStatusSelectComponent>;
    let picked: DeskRunState[];

    const host = (): HTMLElement => fixture.nativeElement as HTMLElement;
    const label = (): string | undefined => host().querySelector('.desk-status__label')?.textContent?.trim();
    const trigger = (): HTMLButtonElement | null => host().querySelector('button.desk-status');
    const menuItems = (): HTMLButtonElement[] =>
        Array.from(document.querySelectorAll<HTMLButtonElement>('.desk-status-menu__item'));
    const tooltip = (): MatTooltip => fixture.debugElement.query(By.directive(MatTooltip)).injector.get(MatTooltip);

    function render(desk: ChatBinding, canChange: boolean): void {
        fixture = TestBed.createComponent(DeskStatusSelectComponent);
        fixture.componentRef.setInput('binding', desk);
        fixture.componentRef.setInput('canChange', canChange);
        picked = [];
        fixture.componentInstance.runStateChange.subscribe((state) => picked.push(state));
        fixture.detectChanges();
    }

    function openMenu(): void {
        trigger()!.click();
        fixture.detectChanges();
    }

    afterEach(() => fixture?.destroy());

    it('says the status with a dot, or for a paused desk the pause mark', () => {
        render(binding({}), false);
        expect(label()).toBe('Live');
        expect(host().querySelector('.desk-status__mark--dot')).not.toBeNull();

        render(binding({ is_active: false }), false);
        expect(label()).toBe('Paused');
        expect(host().querySelector('.desk-status__mark--dot')).toBeNull();
        expect(host().querySelector('.desk-status__mark use')?.getAttribute('href')).toBe('#icon-pause-mark');
    });

    it('is only a status without the right to change it: no button, no menu', () => {
        render(binding({}), false);
        expect(trigger()).toBeNull();
        expect(host().querySelector('.desk-status')?.getAttribute('tabindex')).toBeNull();
    });

    it('offers Live and Paused, with what each means, and names its trigger after the status', () => {
        render(binding({}), true);
        expect(trigger()?.getAttribute('aria-label')).toBe('Desk status: Live. Change');
        openMenu();
        expect(
            menuItems().map((item) => [
                item.querySelector('.desk-status-menu__label')?.textContent?.trim(),
                item.querySelector('.desk-status-menu__description')?.textContent?.trim(),
                item.getAttribute('aria-checked'),
            ])
        ).toEqual([
            ['Live', 'Visitors can chat', 'true'],
            ['Paused', 'Inbox paused. Test lab active.', 'false'],
        ]);
    });

    it('asks for the picked state only when it differs from the current one', () => {
        render(binding({}), true);
        openMenu();
        menuItems()[0].click();
        expect(picked).toEqual([]);

        openMenu();
        menuItems()[1].click();
        expect(picked).toEqual(['paused']);
    });

    it("says a broken desk's reason in a tooltip, focusable even when it cannot be changed", () => {
        render(binding({ broken_reason: 'The flow was deleted.' }), false);
        expect(label()).toBe('Broken');
        expect(host().querySelector('.desk-status')?.getAttribute('tabindex')).toBe('0');
        expect(tooltip().message).toBe('The flow was deleted.');
        expect(tooltip().disabled).toBe(false);

        render(binding({}), false);
        expect(tooltip().disabled).toBe(true);
    });
});
