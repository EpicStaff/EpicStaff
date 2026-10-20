import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter, Router } from '@angular/router';
import { GetMeResponse } from '@shared/models';

import { ChatInboxStreamService } from '../../../features/chat/services/chat-inbox-stream.service';
import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { PermissionsService } from '../../../services/auth/permissions.service';
import { ProfileService } from '../../../services/auth/profile.service';
import { ConfigService } from '../../../services/config';
import { LeftSidebarComponent } from './sidenav.component';
import { TooltipComponent } from './tooltip/tooltip.component';

const COLLAPSED_WIDTH = 60;
const EXPANDED_WIDTH = 240;
const ORG_NAME = 'Acme Research and Development Group';
const DISPLAY_NAME = 'Jane Doe';
const WAITING_COUNT = 4;

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
    let activeOrgId: WritableSignal<number | null>;

    beforeEach(() => {
        activeOrgId = signal<number | null>(1);
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideRouter([
                    { path: 'workspace', children: [] },
                    { path: '**', children: [] },
                ]),
                { provide: ProfileService, useValue: { currentUserSignal: signal(USER) } },
                { provide: ActiveOrgService, useValue: { activeOrgId } },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: () => true,
                        resolveStorageTab: () => 'files',
                        canOpenConfigureModelsDialog: () => true,
                        canAccessWorkspace: () => true,
                    },
                },
                { provide: ConfigService, useValue: { isAuditTrailEnabled: false, isChatEnabled: true } },
                {
                    provide: ChatInboxStreamService,
                    useValue: { waitingCount: signal(WAITING_COUNT), start: vi.fn(), stop: vi.fn() },
                },
            ],
        });

        fixture = TestBed.createComponent(LeftSidebarComponent);
        element = fixture.nativeElement as HTMLElement;
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

    function accountRow(): HTMLElement {
        return element.querySelector<HTMLElement>('.user-avatar-btn')!;
    }

    function logoName(): HTMLElement | null {
        return element.querySelector('.app-logo-name');
    }

    function logoImageAlt(): string | null {
        return element.querySelector('.app-logo img')!.getAttribute('alt');
    }

    function sidebarToggle(): HTMLButtonElement {
        return element.querySelector<HTMLButtonElement>('.logo-container app-sidebar-toggle-button button')!;
    }

    function emittedToggles(): number {
        let count = 0;
        fixture.componentInstance.expandedToggle.subscribe(() => count++);
        sidebarToggle().click();
        return count;
    }

    describe('collapsed', () => {
        beforeEach(() => render(COLLAPSED_WIDTH));

        it('shows only the logo, named by its image', () => {
            expect(logoName()).toBeNull();
            expect(logoImageAlt()).toBe('EpicStaff');
        });

        it('offers an "Open sidebar" control that asks the owner of the width to expand', () => {
            expect(sidebarToggle().getAttribute('aria-label')).toBe('Open sidebar');
            expect(emittedToggles()).toBe(1);
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

        it('shows the product name next to the logo, read once', () => {
            expect(logoName()!.textContent!.trim()).toBe('EpicStaff');
            expect(logoImageAlt()).toBe('');
        });

        it('offers an active "Close sidebar" control that asks the owner of the width to collapse', () => {
            expect(sidebarToggle().getAttribute('aria-label')).toBe('Close sidebar');
            expect(emittedToggles()).toBe(1);
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

        it('shows the active organization and the role in it on the account row, the full name as a title', () => {
            const orgLabel = accountRow().querySelector('.sidenav-row-label')!;

            expect(orgLabel.textContent!.trim()).toBe(ORG_NAME);
            expect(orgLabel.getAttribute('title')).toBe(ORG_NAME);
            expect(accountRow().querySelector('.account-role')!.textContent!.trim()).toBe('Admin');
        });

        it('shows the user on the account row when no organization is active', () => {
            activeOrgId.set(null);
            fixture.detectChanges();

            const userLabel = accountRow().querySelector('.sidenav-row-label')!;
            expect(userLabel.textContent!.trim()).toBe(DISPLAY_NAME);
            expect(userLabel.getAttribute('title')).toBe(DISPLAY_NAME);
        });
    });

    describe('account row', () => {
        beforeEach(() => render(COLLAPSED_WIDTH));

        it.each([
            ['/workspace', true],
            ['/workspace/members', true],
            ['/profile', true],
            ['/profile/overview', true],
            ['/flows', false],
            ['/profiles', false],
        ])('on %s is highlighted: %s', async (url, highlighted) => {
            await TestBed.inject(Router).navigateByUrl(url);
            fixture.detectChanges();

            expect(accountRow().classList.contains('active')).toBe(highlighted);
        });

        it('is highlighted while its menu is open', () => {
            accountRow().click();
            fixture.detectChanges();

            expect(accountRow().classList).toContain('opened');
            expect(element.querySelector('app-user-menu')).not.toBeNull();
        });
    });

    describe('Audit item', () => {
        function separatorBeforeAudit(): boolean {
            const auditItem = navLink('Audit')!.closest('li')!;
            return auditItem.previousElementSibling?.getAttribute('role') === 'separator';
        }

        it('is set off from the pages above it by a separator', () => {
            (TestBed.inject(ConfigService) as { isAuditTrailEnabled: boolean }).isAuditTrailEnabled = true;
            render(COLLAPSED_WIDTH);

            expect(separatorBeforeAudit()).toBe(true);
        });

        it('leaves no separator behind when the audit trail is off', () => {
            render(COLLAPSED_WIDTH);

            expect(navLink('Audit')).toBeUndefined();
            expect(element.querySelector('.main-nav [role="separator"]')).toBeNull();
        });
    });

    describe('Recycle Bin item', () => {
        it('is labelled and active on its pages like the other items', async () => {
            render(EXPANDED_WIDTH);
            await TestBed.inject(Router).navigateByUrl('/recycle-bin/flows');
            fixture.detectChanges();

            expect(labelTexts()).toContain('Recycle Bin');
            expect(navLink('Recycle Bin')!.classList).toContain('active');
        });
    });

    describe('Conversations item', () => {
        beforeEach(() => render(COLLAPSED_WIDTH));

        it('opens the bindings list and stays active on every binding page', async () => {
            const router = TestBed.inject(Router);

            navLink('Conversations')!.click();
            await fixture.whenStable();
            expect(router.url).toBe('/chat-bindings');

            await router.navigateByUrl('/chat-bindings/b-1');
            fixture.detectChanges();
            expect(navLink('Conversations')!.classList).toContain('active');
        });

        it('links its waiting count to the all-bindings inbox', () => {
            const badgeLink = element.querySelector<HTMLAnchorElement>('.sidenav-badge-link')!;

            expect(badgeLink.textContent!.trim()).toBe(String(WAITING_COUNT));
            expect(badgeLink.getAttribute('href')).toBe('/chat-bindings/all');
            expect(badgeLink.getAttribute('aria-label')).toBe('Conversations inbox: 4 waiting for a person');
        });
    });
});
