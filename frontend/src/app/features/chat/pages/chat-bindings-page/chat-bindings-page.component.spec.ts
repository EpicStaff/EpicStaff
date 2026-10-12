import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ActionCode, ResourceCode } from '@shared/models';
import { of, throwError } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { FlowsApiService } from '../../../flows/services/flows-api.service';
import { ChatBindingsDialogComponent } from '../../components/chat-bindings-dialog/chat-bindings-dialog.component';
import { CHAT_BINDING_DEFAULTS, ChatBinding } from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { ChatBindingActionsService } from '../../services/chat-binding-actions.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { ChatBindingsPageComponent } from './chat-bindings-page.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const binding = (overrides: Partial<ChatBinding>): ChatBinding => ({
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

describe('ChatBindingsPageComponent', () => {
    let fixture: ComponentFixture<ChatBindingsPageComponent>;
    const chatApi = { getBindings: vi.fn() };
    const actions = { pause: vi.fn(), resume: vi.fn(), delete: vi.fn(), copySnippet: vi.fn() };
    const dialog = { open: vi.fn() };
    const awaitingByBinding = signal<Record<string, number>>({});
    const awaitingCount = signal(0);
    const permissions: { can: (resource: ResourceCode, action: ActionCode) => boolean } = {
        can: (resource) => resource === ResourceCode.Chats,
    };

    const host = (): HTMLElement => fixture.nativeElement;
    const text = (selector: string): string[] =>
        Array.from(host().querySelectorAll(selector)).map(
            (node) => node.textContent?.replace(/\s+/g, ' ').trim() ?? ''
        );

    function render(bindings: ChatBinding[]): void {
        chatApi.getBindings.mockReturnValue(of(bindings));
        fixture = TestBed.createComponent(ChatBindingsPageComponent);
        fixture.detectChanges();
    }

    function openMenu(index: number): void {
        (host().querySelectorAll('.binding-card__menu-btn')[index] as HTMLButtonElement).click();
        fixture.detectChanges();
    }

    function menuItem(label: string): HTMLButtonElement {
        return Array.from(document.querySelectorAll<HTMLButtonElement>('.binding-card-menu__item')).find(
            (item) => item.textContent?.trim() === label
        ) as HTMLButtonElement;
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.clearAllMocks();
        awaitingByBinding.set({ 'b-2': 3 });
        awaitingCount.set(3);
        dialog.open.mockReturnValue({ closed: of(undefined) });
        TestBed.configureTestingModule({
            imports: [ChatBindingsPageComponent],
            providers: [
                provideRouter([]),
                { provide: ChatApiService, useValue: chatApi },
                { provide: ChatBindingActionsService, useValue: actions },
                { provide: ChatInboxStreamService, useValue: { awaitingByBinding, awaitingCount } },
                {
                    provide: FlowsApiService,
                    useValue: {
                        getGraphsLight: () =>
                            of([
                                { id: 5, name: 'Support flow' },
                                { id: 6, name: 'Sales flow' },
                            ]),
                    },
                },
                { provide: Dialog, useValue: dialog },
                { provide: PermissionsService, useValue: permissions },
                { provide: ToastService, useValue: { error: vi.fn() } },
            ],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('lists the inbox first, then a card per binding by name with its flow, status and waiting count', () => {
        render([
            binding({ id: 'b-2', name: 'Sales', graph_id: 6, is_active: false }),
            binding({ id: 'b-3', name: 'Broken one', graph_id: 9, broken_reason: 'flow deleted' }),
            binding({}),
        ]);
        expect(text('.inbox-card')).toEqual(['Inbox · all bindings 3 waiting for a human']);
        expect(host().querySelector('.inbox-card')?.getAttribute('href')).toBe('/chat-bindings/all');
        expect(text('.binding-card__link')).toEqual(['Broken one', 'Sales', 'Support']);
        expect(text('.binding-card__flow')).toEqual(['Flow #9', 'Sales flow', 'Support flow']);
        expect(text('app-chat-binding-status')).toEqual(['Broken', 'Paused', 'Live']);
        expect(text('.binding-card__waiting')).toEqual(['3 waiting for a human']);
        expect(host().querySelectorAll('.binding-card__link')[2].getAttribute('href')).toBe('/chat-bindings/b-1');
    });

    it('filters the cards by name or flow name', () => {
        render([binding({}), binding({ id: 'b-2', name: 'Sales', graph_id: 6 })]);
        fixture.componentInstance.searchTerm.set('sales fl');
        fixture.detectChanges();
        expect(text('.binding-card__link')).toEqual(['Sales']);
        fixture.componentInstance.searchTerm.set('nothing');
        fixture.detectChanges();
        expect(text('.bindings-grid__no-match')).toEqual(['No bindings match your search.']);
    });

    it('opens the binding dialog in create mode from Create binding and reloads after it closes', () => {
        render([binding({})]);
        const create = Array.from(host().querySelectorAll<HTMLButtonElement>('.header-actions button')).find(
            (button) => button.textContent?.trim() === 'Create binding'
        ) as HTMLButtonElement;
        create.click();
        expect(dialog.open).toHaveBeenCalledWith(
            ChatBindingsDialogComponent,
            expect.objectContaining({ data: { binding: null } })
        );
        expect(chatApi.getBindings).toHaveBeenCalledTimes(2);
    });

    it('shows an empty state with Create binding and no inbox card when there are no bindings', () => {
        render([]);
        expect(text('.empty-state__title')).toEqual(['No chat bindings yet']);
        expect(host().querySelector('.empty-state app-button')).not.toBeNull();
        expect(host().querySelector('.inbox-card')).toBeNull();
    });

    it('shows a load error with Retry instead of the empty state when the bindings fail to load', () => {
        chatApi.getBindings.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500 })));
        render([binding({})]);
        expect(host().querySelector('app-fetch-error-state')).not.toBeNull();
        expect(host().querySelector('.empty-state')).toBeNull();

        (host().querySelector('app-fetch-error-state button') as HTMLButtonElement).click();
        fixture.detectChanges();
        expect(host().querySelector('app-fetch-error-state')).toBeNull();
        expect(text('.binding-card__link')).toEqual(['Support']);
    });

    it('runs the card menu actions and reloads once the server changed the binding', () => {
        const support = binding({});
        render([support]);
        actions.pause.mockReturnValue(of(true));

        openMenu(0);
        expect(menuItem('Resume')).toBeUndefined();
        menuItem('Pause').click();
        expect(actions.pause).toHaveBeenCalledWith(support);
        expect(chatApi.getBindings).toHaveBeenCalledTimes(2);

        openMenu(0);
        menuItem('Edit settings').click();
        expect(dialog.open).toHaveBeenCalledWith(
            ChatBindingsDialogComponent,
            expect.objectContaining({ data: { binding: support } })
        );

        openMenu(0);
        menuItem('Copy snippet').click();
        expect(actions.copySnippet).toHaveBeenCalledWith(support);

        actions.delete.mockReturnValue(of());
        openMenu(0);
        menuItem('Delete').click();
        expect(actions.delete).toHaveBeenCalledWith(support);
    });

    it('offers Resume for a paused binding and hides the update and delete actions without those permissions', () => {
        permissions.can = (resource, action) => resource === ResourceCode.Chats && action === ActionCode.Read;
        try {
            render([binding({ is_active: false })]);
            openMenu(0);
            expect(menuItem('Copy snippet')).toBeDefined();
            expect(menuItem('Resume')).toBeUndefined();
            expect(menuItem('Edit settings')).toBeUndefined();
            expect(menuItem('Delete')).toBeUndefined();
            expect(text('.header-actions app-button')).toEqual([]);
        } finally {
            permissions.can = (resource) => resource === ResourceCode.Chats;
        }
        render([binding({ is_active: false })]);
        openMenu(0);
        expect(menuItem('Resume')).toBeDefined();
    });
});
