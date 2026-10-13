import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { ChatInboxOrder } from '../../models/chat.model';
import { ConversationListToolbarComponent, SEARCH_DEBOUNCE_MS } from './conversation-list-toolbar.component';

describe('ConversationListToolbarComponent', () => {
    let fixture: ComponentFixture<ConversationListToolbarComponent>;
    let searches: string[];
    let orders: ChatInboxOrder[];
    let mineChanges: boolean[];

    const host = (): HTMLElement => fixture.nativeElement as HTMLElement;
    const field = (): HTMLInputElement => host().querySelector('input')!;
    const button = (label: string): HTMLButtonElement | undefined =>
        Array.from(host().querySelectorAll<HTMLButtonElement>('button')).find(
            (candidate) => candidate.textContent?.trim() === label
        );

    function type(value: string): void {
        field().value = value;
        field().dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    function setInputs(
        inputs: Partial<Record<'order' | 'isMineOnly' | 'canFilterMine' | 'searchError', unknown>>
    ): void {
        for (const [name, value] of Object.entries(inputs)) fixture.componentRef.setInput(name, value);
        fixture.detectChanges();
    }

    beforeEach(() => {
        vi.useFakeTimers();
        fixture = TestBed.createComponent(ConversationListToolbarComponent);
        setInputs({ order: 'newest', isMineOnly: false, canFilterMine: true });
        searches = [];
        orders = [];
        mineChanges = [];
        fixture.componentInstance.searchChange.subscribe((search) => searches.push(search));
        fixture.componentInstance.orderChange.subscribe((order) => orders.push(order));
        fixture.componentInstance.mineOnlyChange.subscribe((isMineOnly) => mineChanges.push(isMineOnly));
    });

    afterEach(() => vi.useRealTimers());

    describe('search', () => {
        it('says the trimmed search once typing has settled for 250 ms', () => {
            type('a');
            vi.advanceTimersByTime(100);
            type(' ada ');
            vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 1);
            expect(searches).toEqual([]);

            vi.advanceTimersByTime(1);
            expect(searches).toEqual(['ada']);
        });

        it('says nothing for the same words again, and says a clear at once', () => {
            type('ada');
            vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS);
            type('ada x');
            type('ada');
            vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS);
            expect(searches).toEqual(['ada']);

            type('');
            expect(searches).toEqual(['ada', '']);
        });

        it('clears on Escape at once and keeps the key from anyone else; with nothing typed it lets it through', () => {
            const outside = vi.fn();
            host().addEventListener('keydown', outside);
            type('ada');
            vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS);

            field().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            fixture.detectChanges();
            expect(searches).toEqual(['ada', '']);
            expect(outside).not.toHaveBeenCalled();

            field().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            expect(outside).toHaveBeenCalledTimes(1);
            expect(searches).toEqual(['ada', '']);
        });

        it('drops a search still settling when it is cleared', () => {
            type('ada');
            fixture.componentInstance.clearSearch();
            vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS);
            expect(searches).toEqual(['']);
        });

        it('says why the server refused a search, under the field, as an alert', () => {
            expect(host().querySelector('[role="alert"]')).toBeNull();
            setInputs({ searchError: 'The search must be at most 100 characters.' });
            expect(host().querySelector('[role="alert"]')?.textContent?.trim()).toBe(
                'The search must be at most 100 characters.'
            );
        });
    });

    describe('Mine', () => {
        it('is a toggle button that says whether it is on, and asks for the other state', () => {
            expect(button('Mine')?.getAttribute('aria-pressed')).toBe('false');
            button('Mine')!.click();
            expect(mineChanges).toEqual([true]);

            setInputs({ isMineOnly: true });
            expect(button('Mine')?.getAttribute('aria-pressed')).toBe('true');
            button('Mine')!.click();
            expect(mineChanges).toEqual([true, false]);
        });

        it('is not there without chats use', () => {
            setInputs({ canFilterMine: false });
            expect(button('Mine')).toBeUndefined();
        });
    });

    describe('sort', () => {
        it('shows the order and asks for the other one', () => {
            button('Newest first')!.click();
            expect(orders).toEqual(['oldest']);

            setInputs({ order: 'oldest' });
            button('Oldest first')!.click();
            expect(orders).toEqual(['oldest', 'newest']);
        });

        it('says what it is in its name, starting with what it shows', () => {
            expect(button('Newest first')?.getAttribute('aria-label')).toBe('Sort: newest first');
            setInputs({ order: 'oldest' });
            expect(button('Oldest first')?.getAttribute('aria-label')).toBe('Sort: oldest first');
        });

        it('says which sections it sorts, and that Waiting is always longest wait first', () => {
            const sort = fixture.debugElement
                .queryAll(By.directive(MatTooltip))
                .find((element) => element.nativeElement.textContent?.trim() === 'Newest first')!;
            expect(sort.injector.get(MatTooltip).message).toBe(
                'Sorts In progress, Tests and Bot. Waiting for a person is always longest wait first.'
            );
        });
    });
});
