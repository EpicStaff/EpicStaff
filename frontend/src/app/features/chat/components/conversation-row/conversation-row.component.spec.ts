import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { ProfileService } from '../../../../services/auth/profile.service';
import { ChatConversation } from '../../models/chat.model';
import { ConversationRowComponent, ConversationRowMove } from './conversation-row.component';

// The Take over button collapses its label on overflow, which jsdom cannot measure.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

// Local wall-clock times, so the spoken times ("today at 2:24 PM") hold in any time zone the tests run in.
const NOW = new Date(2026, 9, 12, 14, 30).getTime();
const SIX_MINUTES_AGO = new Date(2026, 9, 12, 14, 24).toISOString();
const TEN_MINUTES_AGO = new Date(2026, 9, 12, 14, 20).toISOString();
const TWENTY_FIVE_MINUTES_AGO = new Date(2026, 9, 12, 14, 5).toISOString();
// Angular's en-US time format may put a narrow no-break space before AM/PM.
const plain = (text: string | null | undefined): string => (text ?? '').replace(/\s+/g, ' ').trim();

const conversation = (overrides: Partial<ChatConversation> = {}): ChatConversation => ({
    id: 'c-1',
    binding_id: 'b-1',
    visitor_number: 1,
    chat_user_id: null,
    mode: 'bot',
    state: 'idle',
    is_test: false,
    assigned_operator_id: null,
    assigned_operator_name: null,
    tokens_used: 0,
    turns: 12,
    tokens_today: 0,
    turns_today: 0,
    last_message_at: SIX_MINUTES_AGO,
    last_message_preview: 'Where is my order?',
    last_message_role: 'user',
    last_message_author_user_id: null,
    last_message_author_name: null,
    handoff_reason: '',
    handoff_at: null,
    visitor_waiting_since: null,
    status: 'open',
    close_reason: null,
    closed_at: null,
    closed_by_user_id: null,
    closed_by_name: null,
    ...overrides,
});

// Handed off ten minutes ago and still waiting for a person.
const waiting = (overrides: Partial<ChatConversation> = {}): ChatConversation =>
    conversation({
        mode: 'awaiting_human',
        handoff_at: TEN_MINUTES_AGO,
        visitor_waiting_since: TEN_MINUTES_AGO,
        status: 'open',
        close_reason: null,
        closed_at: null,
        closed_by_user_id: null,
        closed_by_name: null,
        ...overrides,
    });

describe('ConversationRowComponent', () => {
    let fixture: ComponentFixture<ConversationRowComponent>;

    function render(row: ChatConversation, inputs: Record<string, unknown> = {}): HTMLElement {
        fixture = TestBed.createComponent(ConversationRowComponent);
        fixture.componentRef.setInput('conversation', row);
        fixture.componentRef.setInput('now', NOW);
        Object.entries(inputs).forEach(([key, value]) => fixture.componentRef.setInput(key, value));
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    const host = (): HTMLElement => fixture.nativeElement as HTMLElement;
    const rowButton = (): HTMLButtonElement => host().querySelector('.conversation-row')!;
    const textOf = (selector: string): string => plain(host().querySelector(selector)?.textContent);
    const accessibleName = (): string => plain(rowButton().getAttribute('aria-label'));
    const takeOverButton = (): HTMLButtonElement | null => host().querySelector('.conversation-row__take-over button');
    const tooltipOf = (selector: string): MatTooltip =>
        fixture.debugElement.query(By.css(selector)).injector.get(MatTooltip);

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: ProfileService,
                    useValue: {
                        currentUserSignal: signal({
                            id: 3,
                            display_name: 'Ada Lovelace',
                            email: 'ada@x',
                            avatar_url: null,
                        }),
                    },
                },
            ],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    describe('the visitor', () => {
        it('shows the visitor, the relative time and the last message, without the turns', () => {
            render(conversation({ visitor_number: 12 }));
            expect(textOf('.conversation-row__name')).toBe('Visitor 12');
            expect(textOf('.conversation-row__time')).toBe('6m');
            expect(textOf('.conversation-row__preview')).toBe('Where is my order?');
            expect(host().textContent).not.toContain('turns');
            expect(textOf('app-conversation-avatar')).toBe('12');
            expect(host().querySelector('.conversation-row__desk')).toBeNull();
            expect(tooltipOf('.conversation-row__name').disabled).toBe(true);
        });

        it('names a signed visitor by their verified id, in full in a tooltip', () => {
            render(conversation({ chat_user_id: 'customer-4711@example.com' }));
            expect(textOf('.conversation-row__name')).toBe('customer-4711@example.com');
            expect(accessibleName().startsWith('customer-4711@example.com,')).toBe(true);
            const tooltip = tooltipOf('.conversation-row__name');
            expect(tooltip.disabled).toBe(false);
            expect(tooltip.message).toBe('customer-4711@example.com');
            expect(textOf('app-conversation-avatar')).toBe('CU');
        });
    });

    describe('who wrote last', () => {
        it('puts "You:", another operator\'s name or "Bot:" before the last message, nothing for the visitor', () => {
            render(conversation({ last_message_role: 'operator', last_message_author_user_id: 3 }));
            expect(textOf('.conversation-row__preview')).toBe('You: Where is my order?');

            render(
                conversation({
                    last_message_role: 'operator',
                    last_message_author_user_id: 7,
                    last_message_author_name: 'Grace Hopper',
                })
            );
            expect(textOf('.conversation-row__sender')).toBe('Grace Hopper:');

            render(conversation({ last_message_role: 'operator', last_message_author_user_id: 7 }));
            expect(textOf('.conversation-row__sender')).toBe('Operator #7:');

            render(conversation({ last_message_role: 'assistant' }));
            expect(textOf('.conversation-row__sender')).toBe('Bot:');

            render(conversation({ last_message_role: 'user' }));
            expect(host().querySelector('.conversation-row__sender')).toBeNull();
        });

        it('mutes a system note, which nobody wrote', () => {
            render(conversation({ last_message_role: 'system', last_message_preview: 'Handed off to a person.' }));
            expect(host().querySelector('.conversation-row__sender')).toBeNull();
            expect(host().querySelector('.conversation-row__preview')?.classList).toContain(
                'conversation-row__preview--system'
            );
        });

        it('describes the row with the last message, sender included', () => {
            render(conversation({ last_message_role: 'assistant' }));
            // Looked up inside this row: other specs' leftover markup can reuse the same conversation id.
            const description = host().querySelector(`[id="${rowButton().getAttribute('aria-describedby')}"]`);
            expect(plain(description?.textContent)).toBe('Bot: Where is my order?');
        });

        it('says "Bot is replying…" instead, without a sender, while a run is in flight', () => {
            render(conversation({ state: 'processing', last_message_role: 'user' }));
            expect(textOf('.conversation-row__preview')).toBe('Bot is replying…');
            expect(accessibleName()).toContain('bot is replying');
        });
    });

    describe('waiting for a person', () => {
        it('marks a waiting conversation with a bold name, a dot and how long the visitor has waited', () => {
            render(waiting());
            expect(rowButton().classList).toContain('conversation-row--waiting');
            expect(host().querySelector('.conversation-row__waiting-dot')).not.toBeNull();
            expect(textOf('.conversation-row__waiting')).toBe('10m');

            fixture.componentRef.setInput('now', NOW + 50 * 60_000);
            fixture.detectChanges();
            expect(textOf('.conversation-row__waiting')).toBe('1h');
        });

        it('waits by the waiting time, not the mode: a taken conversation whose visitor wrote again waits too', () => {
            render(
                conversation({
                    mode: 'human',
                    assigned_operator_id: 7,
                    assigned_operator_name: 'Grace Hopper',
                    visitor_waiting_since: TEN_MINUTES_AGO,
                })
            );
            expect(rowButton().classList).toContain('conversation-row--waiting');

            render(conversation({ mode: 'human', assigned_operator_id: 7 }));
            expect(rowButton().classList).not.toContain('conversation-row--waiting');
            expect(host().querySelector('.conversation-row__waiting')).toBeNull();
        });

        it('treats a row without the field (an older chat service) as not waiting, with no Take over', () => {
            const withoutField: Partial<ChatConversation> = { ...conversation() };
            delete withoutField.visitor_waiting_since;
            render(withoutField as ChatConversation, { canTakeOver: true });
            expect(rowButton().classList).not.toContain('conversation-row--waiting');
            expect(host().querySelector('.conversation-row__waiting')).toBeNull();
            expect(takeOverButton()).toBeNull();
            expect(host().textContent).not.toContain('NaN');
            expect(accessibleName()).not.toContain('waiting');
        });

        it('names the row in words, with absolute times so the name stays while the clock ticks', () => {
            render(waiting(), { deskName: 'Sales' });
            const expected =
                'Visitor 1, Sales, last message today at 2:24 PM, waiting for a person since today at 2:20 PM';
            expect(accessibleName()).toBe(expected);
            for (const minutes of [1, 10, 45]) {
                fixture.componentRef.setInput('now', NOW + minutes * 60_000);
                fixture.detectChanges();
                expect(accessibleName()).toBe(expected);
            }
            expect(textOf('.conversation-row__time')).toBe('51m');
        });

        it('marks a test with its chip', () => {
            render(conversation({ is_test: true }));
            expect(textOf('.conversation-row__test-chip')).toBe('Test');
        });
    });

    describe('overdue', () => {
        // A desk whose response time is 10 minutes, then "mark overdue".
        const marksAfterTenMinutes = { style: 'support', overdueAfterMs: 10 * 60_000 } as const;
        const overdueMark = (): Element | null =>
            host().querySelector('.conversation-row__waiting--overdue use[href="#icon-alert-circle"]');

        it('turns the wait into an alert icon in the error colour once past the response time, as the clock ticks', () => {
            render(waiting(), { rules: marksAfterTenMinutes });
            expect(overdueMark()).toBeNull();
            expect(host().querySelector('.conversation-row__waiting-dot')).not.toBeNull();
            expect(accessibleName()).not.toContain('overdue');

            fixture.componentRef.setInput('now', NOW + 60_000);
            fixture.detectChanges();
            expect(overdueMark()).not.toBeNull();
            expect(host().querySelector('.conversation-row__waiting-dot')).toBeNull();
            expect(textOf('.conversation-row__waiting')).toBe('11m');
            expect(tooltipOf('.conversation-row__waiting').disabled).toBe(false);
            expect(tooltipOf('.conversation-row__waiting').message).toBe(
                "Overdue: waiting longer than the desk's response time"
            );
            expect(accessibleName()).toBe(
                'Visitor 1, last message today at 2:24 PM, waiting for a person since today at 2:20 PM, overdue'
            );
        });

        it('marks no one on a desk that does not mark overdue, a desk not known yet, or a test', () => {
            render(waiting({ visitor_waiting_since: TWENTY_FIVE_MINUTES_AGO }), {
                rules: { style: 'support', overdueAfterMs: null },
            });
            expect(overdueMark()).toBeNull();

            render(waiting({ visitor_waiting_since: TWENTY_FIVE_MINUTES_AGO }));
            expect(overdueMark()).toBeNull();

            render(waiting({ visitor_waiting_since: TWENTY_FIVE_MINUTES_AGO, is_test: true }), {
                rules: marksAfterTenMinutes,
            });
            expect(overdueMark()).toBeNull();
        });
    });

    describe('closed', () => {
        const resolved = (overrides: Partial<ChatConversation> = {}): ChatConversation =>
            conversation({
                mode: 'human',
                assigned_operator_id: 7,
                assigned_operator_name: 'Grace Hopper',
                status: 'closed',
                close_reason: 'resolved',
                closed_at: TEN_MINUTES_AGO,
                closed_by_user_id: 7,
                closed_by_name: 'Grace Hopper',
                ...overrides,
            });

        it('says why it closed, muted, with who in a tooltip, and shows the close as its time', () => {
            render(resolved(), { rules: { style: 'support', overdueAfterMs: null } });
            expect(textOf('.conversation-row__closed')).toBe('Resolved');
            expect(tooltipOf('.conversation-row__closed').message).toBe('Resolved by Grace Hopper');
            expect(textOf('.conversation-row__time')).toBe('10m');
            expect(accessibleName()).toBe('Visitor 1, closed today at 2:20 PM, resolved by Grace Hopper');

            render(resolved(), { rules: { style: 'ongoing', overdueAfterMs: null } });
            expect(textOf('.conversation-row__closed')).toBe('Closed');

            render(resolved({ close_reason: 'ended', closed_by_user_id: null, closed_by_name: null }));
            expect(textOf('.conversation-row__closed')).toBe('Ended');
            expect(accessibleName()).toContain('ended by the visitor');

            render(resolved({ close_reason: 'inactive', closed_by_user_id: null, closed_by_name: null }));
            expect(textOf('.conversation-row__closed')).toBe('Inactive');
        });

        it('shows no holder, no wait, no Take over and no replying state: nobody is on it', () => {
            render(resolved({ visitor_waiting_since: TEN_MINUTES_AGO, state: 'processing' }), {
                canTakeOver: true,
                rules: { style: 'support', overdueAfterMs: 60_000 },
            });
            expect(host().querySelector('app-user-avatar')).toBeNull();
            expect(host().querySelector('.conversation-row__waiting')).toBeNull();
            expect(takeOverButton()).toBeNull();
            expect(textOf('.conversation-row__preview')).toBe('Where is my order?');
            expect(accessibleName()).not.toContain('taken by');
        });

        it('marks a closed test as closed beside its Test chip, timed by its last message as Tests sorts it', () => {
            render(resolved({ is_test: true }), { rules: { style: 'support', overdueAfterMs: null } });
            expect(textOf('.conversation-row__test-chip')).toBe('Test');
            expect(textOf('.conversation-row__closed')).toBe('Resolved');
            expect(textOf('.conversation-row__time')).toBe('6m');
            expect(accessibleName()).toBe('Visitor 1, last message today at 2:24 PM, test, resolved by Grace Hopper');
        });
    });

    describe('who holds it', () => {
        it("shows the holder's small avatar and names them: you, their name, or their number", () => {
            render(conversation({ mode: 'human', assigned_operator_id: 3 }));
            expect(textOf('app-user-avatar')).toBe('AL');
            expect(tooltipOf('app-user-avatar').message).toBe('Taken by you');
            expect(accessibleName()).toContain('taken by you');

            render(conversation({ mode: 'human', assigned_operator_id: 7, assigned_operator_name: 'Grace Hopper' }));
            expect(textOf('app-user-avatar')).toBe('GH');
            expect(tooltipOf('app-user-avatar').message).toBe('Taken by Grace Hopper');
            expect(accessibleName()).toContain('taken by Grace Hopper');

            render(conversation({ mode: 'human', assigned_operator_id: 7 }));
            expect(tooltipOf('app-user-avatar').message).toBe('Taken by Operator #7');
            expect(accessibleName()).toContain('taken by Operator #7');
        });
    });

    describe('Take over', () => {
        it('is offered on a waiting row to a user who may take it, and does not also open the row', () => {
            render(waiting(), { canTakeOver: true });
            const opened = vi.fn();
            const takeOver = vi.fn();
            fixture.componentInstance.selectRequested.subscribe(opened);
            fixture.componentInstance.takeOverRequested.subscribe(takeOver);
            expect(takeOverButton()?.getAttribute('aria-label')).toBe('Take over Visitor 1');

            takeOverButton()!.click();
            expect(takeOver).toHaveBeenCalledTimes(1);
            expect(opened).not.toHaveBeenCalled();
        });

        it('is offered on a waiting row another operator holds (the take over then asks), not on one you hold', () => {
            render(waiting({ mode: 'human', assigned_operator_id: 7 }), { canTakeOver: true });
            expect(takeOverButton()).not.toBeNull();

            render(waiting({ mode: 'human', assigned_operator_id: 3 }), { canTakeOver: true });
            expect(takeOverButton()).toBeNull();
        });

        it('is not offered without the permission, on a row nobody waits on, and is disabled while an action runs', () => {
            render(waiting());
            expect(takeOverButton()).toBeNull();

            render(conversation({ mode: 'human', assigned_operator_id: 7 }), { canTakeOver: true });
            expect(takeOverButton()).toBeNull();

            render(waiting(), { canTakeOver: true, isActionPending: true });
            expect(takeOverButton()?.disabled).toBe(true);
        });

        it('moves the focus to the row when pressed, before the button can go away', () => {
            render(waiting(), { canTakeOver: true });
            takeOverButton()!.focus();
            takeOverButton()!.click();
            expect(document.activeElement).toBe(rowButton());
        });
    });

    describe('selection and keys', () => {
        it('marks the open conversation and makes only the tab stop reachable with Tab', () => {
            render(conversation(), { isSelected: true, isTabStop: true });
            expect(rowButton().getAttribute('aria-current')).toBe('true');
            expect(rowButton().tabIndex).toBe(0);

            render(conversation());
            expect(rowButton().hasAttribute('aria-current')).toBe(false);
            expect(rowButton().tabIndex).toBe(-1);
        });

        it('asks to open the conversation on click', () => {
            render(conversation());
            const opened = vi.fn();
            fixture.componentInstance.selectRequested.subscribe(opened);
            rowButton().click();
            expect(opened).toHaveBeenCalledTimes(1);
        });

        it('turns ↑, ↓, Home and End into moves, and leaves other keys alone', () => {
            render(conversation());
            const moves: ConversationRowMove[] = [];
            fixture.componentInstance.moveRequested.subscribe((move) => moves.push(move));
            for (const key of ['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter']) {
                const event = new KeyboardEvent('keydown', { key, cancelable: true });
                rowButton().dispatchEvent(event);
                expect(event.defaultPrevented).toBe(key !== 'Enter');
            }
            expect(moves).toEqual(['next', 'previous', 'first', 'last']);
        });

        it('shows the desk under the visitor when given one (All desks)', () => {
            render(conversation(), { deskName: 'Sales' });
            expect(textOf('.conversation-row__desk')).toBe('Sales');
        });
    });

    describe('compact', () => {
        const rowTooltip = (): MatTooltip => tooltipOf('button.conversation-row');

        it('shows only the avatar, the visitor in a tooltip on the row, and the full accessible name', () => {
            render(waiting(), { isCompact: true });
            expect(rowButton().children).toHaveLength(1);
            expect(rowButton().firstElementChild?.tagName.toLowerCase()).toBe('app-conversation-avatar');
            expect(rowTooltip().message).toBe('Visitor 1');
            expect(rowTooltip().disabled).toBe(false);
            expect(accessibleName()).toMatch(/^Visitor 1, /);
            expect(accessibleName()).toContain('waiting for a person since');
            expect(rowButton().getAttribute('aria-describedby') ?? '').not.toContain('conversation-preview');
        });

        it('names the visitor in a tooltip only while compact', () => {
            render(waiting());
            expect(rowTooltip().disabled).toBe(true);
        });

        it('rings the open conversation instead of filling its row', () => {
            render(conversation(), { isCompact: true, isSelected: true });
            expect(rowButton().classList).toContain('conversation-row--compact');
            expect(rowButton().classList).toContain('conversation-row--selected');
            expect(rowButton().getAttribute('aria-current')).toBe('true');
        });

        it('offers no Take over: there is no room for it', () => {
            render(waiting(), { isCompact: true, canTakeOver: true });
            expect(takeOverButton()).toBeNull();
        });

        it('opens on click and moves with the keys as the full row does', () => {
            render(conversation(), { isCompact: true });
            const opened = vi.fn();
            const moves: ConversationRowMove[] = [];
            fixture.componentInstance.selectRequested.subscribe(opened);
            fixture.componentInstance.moveRequested.subscribe((move) => moves.push(move));

            rowButton().click();
            rowButton().dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', cancelable: true }));
            expect(opened).toHaveBeenCalledTimes(1);
            expect(moves).toEqual(['next']);
        });
    });
});
