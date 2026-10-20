import { signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter, Router } from '@angular/router';
import { GetMeResponse } from '@shared/models';

import { ChatInboxStreamService } from '../../../features/chat/services/chat-inbox-stream.service';
import { AvailablePlugin } from '../../../features/plugins/models/available-plugin.model';
import { AvailablePluginsStorageService } from '../../../features/plugins/services/available-plugins-storage.service';
import { buildAvailablePlugin } from '../../../features/plugins/testing/plugin-fixtures';
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

const WEATHER = buildAvailablePlugin();
const ATLAS = buildAvailablePlugin({
    identifier: 'atlas',
    name: 'Atlas',
    icon_url: '/api/plugin-public/atlas/icon/?v=2.0.0',
    frame_origin: 'https://atlas.plugins.example.com',
});
/** The fixed top items this setup shows, in order (Audit is off). */
const STATIC_TOP_LABELS = ['Agents', 'Tools', 'Storage', 'Flows', 'Chats', 'Conversations'];

describe('LeftSidebarComponent', () => {
    let fixture: ComponentFixture<LeftSidebarComponent>;
    let element: HTMLElement;
    /** What the storage holds: the plugins available in the active organization, sorted by name. */
    let availablePlugins: WritableSignal<AvailablePlugin[]>;

    beforeEach(() => {
        availablePlugins = signal<AvailablePlugin[]>([]);
        TestBed.configureTestingModule({
            providers: [
                { provide: AvailablePluginsStorageService, useValue: { plugins: availablePlugins } },
                provideRouter([
                    { path: 'workspace', children: [] },
                    { path: '**', children: [] },
                ]),
                { provide: ProfileService, useValue: { currentUserSignal: signal(USER) } },
                { provide: ActiveOrgService, useValue: { activeOrgId: signal(1) } },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: () => true,
                        resolveStorageTab: () => 'files',
                        canOpenConfigureModelsDialog: () => true,
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

    function logoName(): HTMLElement | null {
        return element.querySelector('.app-logo-name');
    }

    function logoImageAlt(): string | null {
        return element.querySelector('.app-logo img')!.getAttribute('alt');
    }

    function sidebarToggle(): HTMLButtonElement {
        return element.querySelector<HTMLButtonElement>('.logo-container app-sidebar-toggle-button button')!;
    }

    /** The labels of the top links, in order: the visible text when expanded, the aria-label when collapsed. */
    function topLinkLabels(): string[] {
        return Array.from(element.querySelectorAll<HTMLElement>('.main-nav .sidenav-nav-link')).map(
            (link) =>
                link.querySelector('.sidenav-row-label')?.textContent?.trim() ?? link.getAttribute('aria-label') ?? ''
        );
    }

    function pluginLinks(): HTMLAnchorElement[] {
        return Array.from(element.querySelectorAll<HTMLAnchorElement>('.main-nav a.sidenav-nav-link')).filter((link) =>
            link.getAttribute('href')?.startsWith('/plugins/')
        );
    }

    function showPlugins(plugins: AvailablePlugin[]): void {
        availablePlugins.set(plugins);
        fixture.detectChanges();
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
            expect(sidebarToggle().classList).toContain('active');
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

    describe('plugin items', () => {
        it('come after the fixed items, one per available plugin, in the order the storage gives', () => {
            render(EXPANDED_WIDTH);

            showPlugins([ATLAS, WEATHER]);

            expect(topLinkLabels()).toEqual([...STATIC_TOP_LABELS, 'Atlas', 'Weather']);
        });

        it("link to the plugin's page, show its name and draw its own icon as an image", () => {
            render(EXPANDED_WIDTH);
            showPlugins([WEATHER]);

            const [link] = pluginLinks();
            expect(link.getAttribute('href')).toBe('/plugins/weather');
            expect(link.querySelector('.sidenav-row-label')!.textContent!.trim()).toBe('Weather');
            expect(link.hasAttribute('aria-label')).toBe(false);
            expect(link.querySelector('.sidenav-link-icon img')!.getAttribute('src')).toBe(WEATHER.icon_url);
            expect(link.querySelector('app-svg-icon')).toBeNull();

            render(COLLAPSED_WIDTH);
            expect(pluginLinks()[0].getAttribute('aria-label')).toBe('Weather');
        });

        it('stay active on every page of their own plugin, and only there', async () => {
            render(EXPANDED_WIDTH);
            showPlugins([ATLAS, WEATHER]);
            const router = TestBed.inject(Router);
            const activeHrefs = (): string[] =>
                pluginLinks()
                    .filter((link) => link.classList.contains('active'))
                    .map((link) => link.getAttribute('href')!);

            await router.navigateByUrl('/plugins/weather/forecast?city=Rome');
            fixture.detectChanges();
            expect(activeHrefs()).toEqual(['/plugins/weather']);

            await router.navigateByUrl('/plugins/weathers');
            fixture.detectChanges();
            expect(activeHrefs()).toEqual([]);
        });

        it('are absent when no plugin is available (platform off, no organization, or none granted)', () => {
            render(EXPANDED_WIDTH);

            expect(pluginLinks()).toEqual([]);
            expect(topLinkLabels()).toEqual(STATIC_TOP_LABELS);
        });

        it('follow the list: cleared on an org switch, back when the new list arrives', () => {
            render(EXPANDED_WIDTH);
            showPlugins([WEATHER]);
            expect(pluginLinks().map((link) => link.getAttribute('href'))).toEqual(['/plugins/weather']);

            showPlugins([]);
            expect(pluginLinks()).toEqual([]);

            showPlugins([ATLAS]);
            expect(pluginLinks().map((link) => link.getAttribute('href'))).toEqual(['/plugins/atlas']);
        });

        it("show the plugin's name as a tooltip on hover when collapsed", () => {
            render(COLLAPSED_WIDTH);
            showPlugins([WEATHER]);

            hoverItem('Weather');

            expect(visibleTooltipTexts()).toContain('Weather');
        });
    });
});
