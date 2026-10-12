import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';

import { ChatInboxStreamService } from '../../../features/chat/services/chat-inbox-stream.service';
import { EpicChatService } from '../../../features/epic-chat/epic-chat.service';
import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { AuthService } from '../../../services/auth/auth.service';
import { PermissionsService } from '../../../services/auth/permissions.service';
import { ProfileService } from '../../../services/auth/profile.service';
import { ConfigService } from '../../../services/config';
import { EasterEggTriggerService } from '../../../services/easter-egg-trigger.service';
import { LeftSidebarComponent } from './sidenav.component';

// The nav config only: the real template pulls in the org/user menus and the EpicChat widget.
describe('LeftSidebarComponent chat item', () => {
    let component: LeftSidebarComponent;

    beforeEach(() => {
        TestBed.configureTestingModule({
            imports: [LeftSidebarComponent],
            providers: [
                provideRouter([{ path: '**', children: [] }]),
                { provide: ProfileService, useValue: { currentUserSignal: signal(null) } },
                { provide: EasterEggTriggerService, useValue: {} },
                { provide: EpicChatService, useValue: {} },
                { provide: ActiveOrgService, useValue: {} },
                {
                    provide: ConfigService,
                    useValue: { isEpicChatEnabled: false, apiUrl: '/api/', isChatEnabled: true },
                },
                { provide: AuthService, useValue: { accessToken: signal(null) } },
                { provide: PermissionsService, useValue: { can: () => true, resolveStorageTab: () => null } },
                { provide: ChatInboxStreamService, useValue: { awaitingCount: signal(4), stop: vi.fn() } },
            ],
        });
        TestBed.overrideComponent(LeftSidebarComponent, { set: { template: '', imports: [] } });
        component = TestBed.createComponent(LeftSidebarComponent).componentInstance;
    });

    it('opens the bindings list, stays active on every binding page and links its badge to the all-bindings inbox', async () => {
        const chat = component.topNavItems.find((item) => item.id === 'chat')!;
        expect(component.resolveRouteLink(chat)).toBe('chat-bindings');
        expect(chat.badgeLink).toBe('/chat-bindings/all');
        expect(component.badgeCount(chat)).toBe(4);
        expect(chat.badgeLabel?.(4)).toBe('Chat inbox: 4 waiting for a human');

        await TestBed.inject(Router).navigateByUrl('/chat-bindings/b-1');
        expect(component.isItemActive(chat)).toBe(true);
    });
});
