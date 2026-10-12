import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter, Router } from '@angular/router';
import { GetMeResponse } from '@shared/models';

import { EpicChatService } from '../../../features/epic-chat/epic-chat.service';
import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { AuthService } from '../../../services/auth/auth.service';
import { PermissionsService } from '../../../services/auth/permissions.service';
import { ProfileService } from '../../../services/auth/profile.service';
import { ConfigService } from '../../../services/config';
import { LeftSidebarComponent } from './sidenav.component';
import { TooltipComponent } from './tooltip/tooltip.component';

const COLLAPSED_WIDTH = 60;
const EXPANDED_WIDTH = 240;
const ORG_NAME = 'Acme Research and Development Group';
const DISPLAY_NAME = 'Jane Doe';

const USER = {
    id: 7,
    email: 'jane@example.com',
    display_name: DISPLAY_NAME,
    avatar_url: null,
    memberships: [{ organization: { id: 1, name: ORG_NAME }, role: { name: 'Admin' } }],
} as unknown as GetMeResponse;

describe('LeftSidebarComponent', () => {
    let fixture: ComponentFixture<LeftSidebarComponent>;
    let element: HTMLElement;
    const isDocked = signal(false);

    beforeEach(() => {
        // The component reconnects EpicChat agents on a 2s timer after rendering.
        vi.useFakeTimers({ toFake: ['setTimeout'] });
        isDocked.set(false);

        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    { path: 'workspace', children: [] },
                    { path: '**', children: [] },
                ]),
                { provide: ProfileService, useValue: { currentUserSignal: signal(USER) } },
                { provide: ActiveOrgService, useValue: { activeOrgId: signal(1) } },
                { provide: AuthService, useValue: { accessToken: signal('token') } },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: () => true,
                        resolveStorageTab: () => 'files',
                        canOpenConfigureModelsDialog: () => true,
                    },
                },
                { provide: ConfigService, useValue: { isEpicChatEnabled: true, apiUrl: 'http://api/' } },
                {
                    provide: EpicChatService,
                    useValue: {
                        isDocked,
                        isChatOpen: signal(false),
                        dockWidth: signal(420),
                        epChatCommand: signal(null),
                        reconnectAgents: vi.fn(),
                    },
                },
            ],
        });

        fixture = TestBed.createComponent(LeftSidebarComponent);
        element = fixture.nativeElement as HTMLElement;
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    function render(width: number): void {
        fixture.componentRef.setInput('width', width);
        fixture.detectChanges();
    }

    function navLink(label: string): HTMLElement | undefined {
        return Array.from(element.querySelectorAll<HTMLElement>('.sidenav-nav-link')).find(
            (link) =>
                link.getAttribute('aria-label') === label ||
                link.querySelector('.sidenav-row-label')?.textContent?.trim() === label
        );
    }

    function labelTexts(): string[] {
        return Array.from(element.querySelectorAll('.sidenav-row-label')).map((label) => label.textContent!.trim());
    }

    function hoverItem(label: string): void {
        navLink(label)!.closest('li')!.dispatchEvent(new MouseEvent('mouseenter'));
        fixture.detectChanges();
    }

    function visibleTooltipTexts(): string[] {
        return fixture.debugElement
            .queryAll(By.directive(TooltipComponent))
            .map((tooltip) => tooltip.componentInstance as TooltipComponent)
            .filter((tooltip) => tooltip.visible)
            .map((tooltip) => tooltip.text);
    }

    function epicChatLeft(): string | null {
        return element.querySelector('epic-chat')!.getAttribute('chat-left');
    }

    function logoName(): HTMLElement | null {
        return element.querySelector('.app-logo-name');
    }

    function logoImageAlt(): string | null {
        return element.querySelector('.app-logo img')!.getAttribute('alt');
    }

    function hoverLogo(): void {
        element.querySelector('.app-logo')!.dispatchEvent(new MouseEvent('mouseenter'));
        fixture.detectChanges();
    }

    describe('collapsed', () => {
        beforeEach(() => render(COLLAPSED_WIDTH));

        it('shows only the logo, named by its image, with the product name as a hover tooltip', () => {
            expect(logoName()).toBeNull();
            expect(logoImageAlt()).toBe('EpicStaff.ai');

            hoverLogo();

            expect(visibleTooltipTexts()).toContain('EpicStaff.ai');
        });

        it('renders icons only and names each link with an aria-label', () => {
            expect(labelTexts()).toEqual([]);
            expect(navLink('Agents')!.getAttribute('aria-label')).toBe('Agents');
            expect(navLink('Settings')!.getAttribute('aria-label')).toBe('Settings');
        });

        it('shows the label as a tooltip on hover', () => {
            hoverItem('Flows');

            expect(visibleTooltipTexts()).toContain('Flows');
        });
    });

    describe('expanded', () => {
        beforeEach(() => render(EXPANDED_WIDTH));

        it('shows the product name next to the logo, read once, without a tooltip', () => {
            expect(logoName()!.textContent!.trim()).toBe('EpicStaff.ai');
            expect(logoImageAlt()).toBe('');

            hoverLogo();

            expect(visibleTooltipTexts()).not.toContain('EpicStaff.ai');
        });

        it('shows the labels as text and drops the aria-label so they are not announced twice', () => {
            expect(labelTexts()).toEqual(expect.arrayContaining(['Agents', 'Flows', 'Settings']));
            expect(navLink('Agents')!.hasAttribute('aria-label')).toBe(false);
            expect(navLink('Settings')!.hasAttribute('aria-label')).toBe(false);
        });

        it('suppresses the hover tooltips', () => {
            hoverItem('Flows');

            expect(visibleTooltipTexts()).not.toContain('Flows');
        });

        it('shows the full org and user names as titles for truncated labels', () => {
            const orgLabel = element.querySelector('.org-menu-btn .sidenav-row-label')!;
            const userLabel = element.querySelector('.user-avatar-btn .sidenav-row-label')!;

            expect(orgLabel.textContent!.trim()).toBe(ORG_NAME);
            expect(orgLabel.getAttribute('title')).toBe(ORG_NAME);
            expect(userLabel.textContent!.trim()).toBe(DISPLAY_NAME);
            expect(userLabel.getAttribute('title')).toBe(DISPLAY_NAME);
        });

        it('labels the org switcher "Workspace" on workspace pages', async () => {
            await TestBed.inject(Router).navigateByUrl('/workspace');
            fixture.detectChanges();

            const orgLabel = element.querySelector('.org-menu-btn .sidenav-row-label')!;
            expect(orgLabel.textContent!.trim()).toBe('Workspace');
        });
    });

    describe('EpicChat position', () => {
        it('opens the floating chat just beside the sidebar edge', () => {
            render(COLLAPSED_WIDTH);
            expect(epicChatLeft()).toBe('68px');

            render(EXPANDED_WIDTH);
            expect(epicChatLeft()).toBe('248px');
        });

        it('starts the docked chat exactly at the sidebar edge', () => {
            isDocked.set(true);

            render(COLLAPSED_WIDTH);
            expect(epicChatLeft()).toBe('60px');

            render(EXPANDED_WIDTH);
            expect(epicChatLeft()).toBe('240px');
        });
    });
});
