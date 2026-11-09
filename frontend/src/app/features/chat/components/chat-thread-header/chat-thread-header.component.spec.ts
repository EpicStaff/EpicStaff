import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { PhoneLayoutService } from '../../../../core/services/phone-layout.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { ChatBinding, ChatConversation } from '../../models/chat.model';
import { ChatConversationActionsService } from '../../services/chat-conversation-actions.service';
import { OpenConversationService } from '../../services/open-conversation.service';
import { ChatThreadHeaderComponent } from './chat-thread-header.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const CONVERSATION_ID = '3f2b8c1e-9a4d-4e7b-8c21-5d6f0a1b2c3d';
const CURRENT_USER_ID = 3;
const NOW = Date.parse('2026-03-02T14:30:00Z');
const TEN_MINUTES_AGO = new Date(NOW - 10 * 60_000).toISOString();
const ELEVEN_MINUTES_AGO = new Date(NOW - 11 * 60_000).toISOString();
const OVERDUE_NOTE = "Overdue: waiting longer than the desk's response time";
const SUPPORT_DESK: Partial<ChatBinding> = { name: 'Support desk', style: 'support' };
// A Support desk whose response time is 10 minutes, then "mark overdue".
const MARKS_AFTER_TEN_MINUTES: Partial<ChatBinding> = {
    name: 'Support desk',
    style: 'support',
    response_time_seconds: 600,
    on_response_timeout: 'overdue',
};

const conversation = (overrides: Partial<ChatConversation> = {}): ChatConversation => ({
    id: CONVERSATION_ID,
    binding_id: 'b-1',
    mode: 'bot',
    state: 'idle',
    is_test: false,
    assigned_operator_id: null,
    tokens_used: 0,
    turns: 0,
    tokens_today: 0,
    turns_today: 0,
    last_message_at: null,
    last_message_preview: '',
    handoff_reason: '',
    handoff_at: null,
    visitor_number: 12,
    chat_user_id: null,
    assigned_operator_name: null,
    last_message_role: 'user',
    last_message_author_user_id: null,
    last_message_author_name: null,
    visitor_waiting_since: null,
    status: 'open',
    close_reason: null,
    closed_at: null,
    closed_by_user_id: null,
    closed_by_name: null,
    ...overrides,
});

describe('ChatThreadHeaderComponent', () => {
    let fixture: ComponentFixture<ChatThreadHeaderComponent>;
    const isPhone = signal(false);
    const toast = { success: vi.fn(), error: vi.fn() };
    let writeText: ReturnType<typeof vi.fn>;
    let canUse = true;

    const host = (): HTMLElement => fixture.nativeElement;
    const text = (selector: string): string =>
        host().querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    const tooltipOf = (selector: string): MatTooltip | null =>
        fixture.debugElement.query(By.css(selector))?.injector.get(MatTooltip, null) ?? null;
    const idButton = (): HTMLButtonElement => host().querySelector('.thread-header__id') as HTMLButtonElement;
    const copyIconButton = (): HTMLButtonElement =>
        host().querySelector('button[aria-label="Copy conversation ID"]') as HTMLButtonElement;
    const copyIcon = (): string | null => copyIconButton().querySelector('use')?.getAttribute('href') ?? null;
    const menuItems = (): HTMLButtonElement[] =>
        Array.from(document.querySelectorAll<HTMLButtonElement>('.chat-action-menu__item'));

    /** Opens the ⋯ menu (the desktop's or the phone's, whichever shows) and reads its items. */
    function menuLabels(): string[] {
        host().querySelector<HTMLButtonElement>('.chat-action-menu__trigger')?.click();
        fixture.detectChanges();
        return menuItems().map((item) => item.textContent?.trim() ?? '');
    }

    function choose(label: string): void {
        menuLabels();
        menuItems()
            .find((item) => item.textContent?.trim() === label)
            ?.click();
        fixture.detectChanges();
    }

    function render(overrides: Partial<ChatConversation> = {}): void {
        fixture = TestBed.createComponent(ChatThreadHeaderComponent);
        fixture.componentRef.setInput('conversation', conversation(overrides));
        fixture.detectChanges();
    }

    function renderOn(desk: Partial<ChatBinding>, overrides: Partial<ChatConversation> = {}): void {
        fixture = TestBed.createComponent(ChatThreadHeaderComponent);
        fixture.componentRef.setInput('binding', desk);
        fixture.componentRef.setInput('conversation', conversation(overrides));
        fixture.detectChanges();
    }

    async function settle(milliseconds = 0): Promise<void> {
        await vi.advanceTimersByTimeAsync(milliseconds);
        fixture.detectChanges();
    }

    beforeEach(() => {
        vi.useFakeTimers();
        vi.setSystemTime(NOW);
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.clearAllMocks();
        isPhone.set(false);
        canUse = true;
        writeText = vi.fn(() => Promise.resolve());
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
        TestBed.configureTestingModule({
            imports: [ChatThreadHeaderComponent],
            providers: [
                { provide: PhoneLayoutService, useValue: { isPhone } },
                { provide: PermissionsService, useValue: { can: () => canUse } },
                { provide: ProfileService, useValue: { currentUserSignal: signal({ id: CURRENT_USER_ID }) } },
                { provide: ChatConversationActionsService, useValue: { isPending: signal(false) } },
                { provide: OpenConversationService, useValue: { close: vi.fn() } },
                { provide: ToastService, useValue: toast },
            ],
        });
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
        Reflect.deleteProperty(navigator, 'clipboard');
    });

    it('names the visitor over the path and the full conversation id, without the desk', () => {
        render();
        fixture.componentRef.setInput('binding', { name: 'Support desk' });
        fixture.detectChanges();

        expect(text('.thread-header__visitor')).toBe('Visitor 12');
        expect(text('.thread-header__path')).toBe(`Bot / ${CONVERSATION_ID}`);
        expect(host().textContent).not.toContain('Support desk');
    });

    it.each([
        { case: 'with the bot', overrides: {}, path: 'Bot /' },
        { case: 'awaiting a person', overrides: { mode: 'awaiting_human' as const }, path: 'Bot /' },
        { case: 'taken over', overrides: { mode: 'human' as const }, path: 'Bot / Human /' },
        {
            case: 'closed after a take over',
            overrides: { mode: 'human' as const, status: 'closed' as const },
            path: 'Bot / Human /',
        },
    ])('says the path of a conversation $case: $path', ({ overrides, path }) => {
        render(overrides);
        expect(text('.thread-header__trail')).toBe(path);
    });

    it('explains Bot / Human in a tooltip, and Bot alone has none', () => {
        render({ mode: 'human' });
        expect(tooltipOf('.thread-header__trail')?.message).toBe(
            'The bot and an operator took part in this conversation'
        );

        fixture.componentRef.setInput('conversation', conversation({ mode: 'bot' }));
        fixture.detectChanges();
        expect(tooltipOf('.thread-header__trail')).toBeNull();
    });

    it('shows no mode pill on desktop: the path says Bot or Bot / Human', () => {
        render({ mode: 'human', assigned_operator_id: CURRENT_USER_ID });
        expect(host().querySelector('.mode-badge')).toBeNull();
        expect(host().textContent).not.toContain('Held by');
    });

    describe('the wait chip', () => {
        const chip = (): HTMLElement | null => host().querySelector('.thread-header__wait');
        const chipIcon = (): string | null => chip()?.querySelector('use')?.getAttribute('href') ?? null;
        // Visible text only: the chip also carries words for screen readers.
        const chipDuration = (): string =>
            Array.from(chip()?.childNodes ?? [])
                .filter((node) => node.nodeType === Node.TEXT_NODE)
                .map((node) => node.textContent?.trim())
                .join('');

        it('sits right of the visitor name while they wait, counting the seconds', async () => {
            renderOn({ name: 'Support desk' }, { mode: 'awaiting_human', visitor_waiting_since: TEN_MINUTES_AGO });

            expect(chip()?.previousElementSibling?.matches('.thread-header__visitor')).toBe(true);
            expect(chipDuration()).toBe('10m 0s');
            expect(chipIcon()).toBe('#icon-clock');

            await settle(16_000);
            expect(chipDuration()).toBe('10m 16s');
        });

        it.each([
            { case: 'nobody waits', overrides: {} },
            {
                case: 'the conversation is closed',
                overrides: { status: 'closed' as const, visitor_waiting_since: TEN_MINUTES_AGO },
            },
        ])('is not there when $case', ({ overrides }) => {
            renderOn({ name: 'Support desk' }, overrides);
            expect(chip()).toBeNull();
        });

        it("turns overdue past the desk's response time, as the clock ticks", async () => {
            renderOn(MARKS_AFTER_TEN_MINUTES, { mode: 'awaiting_human', visitor_waiting_since: TEN_MINUTES_AGO });
            expect(chip()?.classList).not.toContain('thread-header__wait--overdue');

            await settle(1_000);
            expect(chip()?.classList).toContain('thread-header__wait--overdue');
            expect(chipIcon()).toBe('#icon-alert-circle');
        });

        it.each([
            {
                case: 'overdue, with a reason',
                since: ELEVEN_MINUTES_AGO,
                reason: 'Asked for a refund',
                expected: `${OVERDUE_NOTE} · Asked for a refund`,
            },
            { case: 'overdue, no reason', since: ELEVEN_MINUTES_AGO, reason: '', expected: OVERDUE_NOTE },
            {
                case: 'in time, with a reason',
                since: TEN_MINUTES_AGO,
                reason: 'Asked for a refund',
                expected: 'Asked for a refund',
            },
        ])('says in its tooltip what applies when $case', ({ since, reason, expected }) => {
            renderOn(MARKS_AFTER_TEN_MINUTES, {
                mode: 'awaiting_human',
                visitor_waiting_since: since,
                handoff_reason: reason,
            });
            expect(tooltipOf('.thread-header__wait')?.message).toBe(expected);
            expect(tooltipOf('.thread-header__wait')?.disabled).toBe(false);
            expect(chip()?.getAttribute('tabindex')).toBe('0');
        });

        it('has no tooltip, and takes no focus, in time and without a reason', () => {
            renderOn(MARKS_AFTER_TEN_MINUTES, { mode: 'awaiting_human', visitor_waiting_since: TEN_MINUTES_AGO });
            expect(tooltipOf('.thread-header__wait')?.disabled).toBe(true);
            expect(chip()?.hasAttribute('tabindex')).toBe(false);
        });

        it('leaves a stale handoff reason out once the conversation is back with the bot', () => {
            renderOn(MARKS_AFTER_TEN_MINUTES, {
                mode: 'bot',
                visitor_waiting_since: TEN_MINUTES_AGO,
                handoff_reason: 'Asked for a refund',
            });
            expect(tooltipOf('.thread-header__wait')?.message ?? '').not.toContain('Asked for a refund');
        });
    });

    describe('the main action', () => {
        const action = (): HTMLElement | null => host().querySelector('.thread-header__action');

        it.each([
            { holder: 'the user', overrides: { mode: 'human' as const, assigned_operator_id: CURRENT_USER_ID } },
            { holder: 'another operator', overrides: { mode: 'human' as const, assigned_operator_id: 99 } },
            { holder: 'nobody', overrides: {} },
            { holder: 'nobody, on a test', overrides: { is_test: true } },
        ])('is Resolve on a Support desk when held by $holder, first on the right with its check', ({ overrides }) => {
            renderOn(SUPPORT_DESK, overrides);

            expect(text('.thread-header__action')).toBe('Resolve');
            expect(action()?.querySelector('use')?.getAttribute('href')).toBe('#icon-check-small');
            expect(action()?.nextElementSibling?.classList).toContain('thread-header__usage');
            expect(menuLabels()).not.toContain('Resolve');
        });

        it('is none on a closed conversation', () => {
            renderOn(SUPPORT_DESK, { mode: 'human', status: 'closed' });
            expect(action()).toBeNull();
        });
    });

    describe('the ⋯ menu', () => {
        it("keeps Take over and Hand Back to Bot on another operator's conversation, then Copy Visitor ID", () => {
            renderOn(SUPPORT_DESK, { mode: 'human', assigned_operator_id: 99 });
            expect(menuLabels()).toEqual(['Take over', 'Hand Back to Bot', 'Copy Visitor ID']);
        });

        it("is there with Copy Visitor ID alone on the bot's conversation, whose only action has the button", () => {
            renderOn(SUPPORT_DESK);
            expect(menuLabels()).toEqual(['Copy Visitor ID']);
        });

        it.each([
            { case: 'a closed conversation', overrides: { status: 'closed' as const }, mayUse: true },
            { case: 'a user without chats use', overrides: {}, mayUse: false },
        ])('still offers Copy Visitor ID on $case', ({ overrides, mayUse }) => {
            canUse = mayUse;
            renderOn(SUPPORT_DESK, overrides);
            expect(menuLabels()).toEqual(['Copy Visitor ID']);
        });

        it('offers it on phones too, after the main action that leads the menu there', () => {
            isPhone.set(true);
            renderOn(SUPPORT_DESK);
            expect(menuLabels()).toEqual(['Resolve', 'Copy Visitor ID']);
        });

        it('puts Delete Conversation after it, set apart, for whoever may delete', () => {
            renderOn(SUPPORT_DESK);
            fixture.componentRef.setInput('canDelete', true);
            fixture.detectChanges();

            expect(menuLabels()).toEqual(['Copy Visitor ID', 'Delete Conversation']);
            expect(
                document.querySelector('.chat-action-menu__separator')?.nextElementSibling?.textContent?.trim()
            ).toBe('Delete Conversation');
        });

        it.each([
            { visitor: 'a signed visitor', overrides: { chat_user_id: 'customer-881' }, copied: 'customer-881' },
            { visitor: 'an anonymous visitor', overrides: {}, copied: '12' },
        ])('copies the id of $visitor and confirms it', async ({ overrides, copied }) => {
            renderOn(SUPPORT_DESK, overrides);
            choose('Copy Visitor ID');
            await settle();

            expect(writeText).toHaveBeenCalledWith(copied);
            expect(toast.success).toHaveBeenCalledWith('Visitor ID copied', 3000, 'bottom-right');
        });
    });

    it.each([
        { target: 'the copy icon', button: copyIconButton },
        { target: 'the id itself', button: idButton },
    ])('copies the full id from $target and confirms it', async ({ button }) => {
        render();
        button().click();
        await settle();

        expect(writeText).toHaveBeenCalledWith(CONVERSATION_ID);
        expect(toast.success).toHaveBeenCalledWith('Conversation ID copied', 3000, 'bottom-right');
    });

    it('turns the copy icon into a check for two seconds, then back', async () => {
        render();
        expect(copyIcon()).toBe('#icon-copy-small');

        copyIconButton().click();
        await settle();
        expect(copyIcon()).toBe('#icon-check-small');

        await settle(1999);
        expect(copyIcon()).toBe('#icon-check-small');
        await settle(1);
        expect(copyIcon()).toBe('#icon-copy-small');
    });

    it('shows the copy icon again for another conversation', async () => {
        render();
        copyIconButton().click();
        await settle();

        fixture.componentRef.setInput('conversation', conversation({ id: 'another-conversation' }));
        fixture.detectChanges();
        expect(copyIcon()).toBe('#icon-copy-small');
    });

    it('shows no check on another conversation when the copy finishes after the switch', async () => {
        let finishCopy: () => void = () => undefined;
        writeText.mockReturnValue(new Promise<void>((resolve) => (finishCopy = resolve)));
        render();
        copyIconButton().click();

        fixture.componentRef.setInput('conversation', conversation({ id: 'another-conversation' }));
        fixture.detectChanges();
        finishCopy();
        await settle();

        expect(copyIcon()).toBe('#icon-copy-small');
    });

    it('keeps the check for two seconds from the latest copy', async () => {
        render();
        copyIconButton().click();
        await settle(1500);
        copyIconButton().click();
        await settle(1500);

        expect(copyIcon()).toBe('#icon-check-small');
        await settle(500);
        expect(copyIcon()).toBe('#icon-copy-small');
    });

    it('keeps the copy icon and reports the failure when the clipboard refuses', async () => {
        writeText.mockReturnValue(Promise.reject(new Error('denied')));
        render();
        copyIconButton().click();
        await settle();

        expect(copyIcon()).toBe('#icon-copy-small');
        expect(toast.error).toHaveBeenCalledWith('Failed to copy', 3000, 'top-right');
        expect(toast.success).not.toHaveBeenCalled();
    });

    it('keeps the handoff reason as a line under the row on phones, not in the mode pill tooltip', () => {
        isPhone.set(true);
        render({ mode: 'awaiting_human', assigned_operator_id: CURRENT_USER_ID, handoff_reason: 'Asked for a refund' });

        expect(text('.thread-header__reason')).toBe('Asked for a refund');
        expect(tooltipOf('.mode-badge')?.message).toBe('Held by you');
        expect(host().querySelector('.thread-header__identity')).toBeNull();
    });

    it.each([
        { holder: 'the user', overrides: { assigned_operator_id: CURRENT_USER_ID }, shown: 'Held by you' },
        { holder: 'an operator not named yet', overrides: { assigned_operator_id: 7 }, shown: 'Held by Operator #7' },
        {
            holder: 'a named operator',
            overrides: { assigned_operator_id: 7, assigned_operator_name: 'Grace Hopper' },
            shown: 'Held by Grace Hopper',
        },
    ])('names who holds it in the mode pill tooltip on phones: $holder', async ({ overrides, shown }) => {
        isPhone.set(true);
        render({ mode: 'human', ...overrides });

        const pill = host().querySelector('.mode-badge') as HTMLElement;
        expect(pill.getAttribute('tabindex')).toBe('0');
        pill.dispatchEvent(new MouseEvent('mouseenter'));
        await settle();
        expect(document.querySelector('.mat-mdc-tooltip')?.textContent?.trim()).toBe(shown);
    });
});
