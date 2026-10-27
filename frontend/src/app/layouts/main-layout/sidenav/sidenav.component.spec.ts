import { InteractivityChecker } from '@angular/cdk/a11y';
import { Dialog } from '@angular/cdk/dialog';
import { OverlayContainer } from '@angular/cdk/overlay';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter, Router } from '@angular/router';
import { GetMeResponse, ResourceCode } from '@shared/models';

import { ProfileTourProgressStore, TOUR_PROGRESS_STORE } from '../../../core/guided-tour';
import { ChatInboxStreamService } from '../../../features/chat/services/chat-inbox-stream.service';
import { AvailablePlugin } from '../../../features/plugins/models/available-plugin.model';
import { AppReturnUrlService } from '../../../features/plugins/services/app-return-url.service';
import { AvailablePluginsStorageService } from '../../../features/plugins/services/available-plugins-storage.service';
import {
    buildAvailablePlugin,
    buildAvailablePluginNavigationItem,
} from '../../../features/plugins/testing/plugin-fixtures';
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
    description: 'Maps of everything',
    icon_url: '/api/plugin-public/atlas/icon/?v=2.0.0',
    frame_origin: 'https://atlas.plugins.example.com',
    navigation: [
        buildAvailablePluginNavigationItem({
            label: 'Overview',
            path: '/',
            icon_url: '/api/plugin-public/atlas/icons/overview.svg/?v=2.0.0',
        }),
        buildAvailablePluginNavigationItem({
            label: 'Projects',
            path: '/projects',
            icon_url: '/api/plugin-public/atlas/icons/projects.svg/?v=2.0.0',
        }),
        buildAvailablePluginNavigationItem({
            label: 'Reports',
            path: '/reports',
            icon_url: '/api/plugin-public/atlas/icons/reports.svg/?v=2.0.0',
        }),
    ],
});
/** The fixed top items this setup shows, in order (Audit is off). */
const STATIC_TOP_LABELS = ['Agents', 'Tools', 'Virtual Environments', 'Storage', 'Flows', 'Chats', 'Conversations'];

/** Everything counts as on screen: jsdom lays nothing out, so the focus trap would find nothing to focus. */
class LaidOutInteractivityChecker extends InteractivityChecker {
    override isVisible(): boolean {
        return true;
    }
}

describe('LeftSidebarComponent', () => {
    let fixture: ComponentFixture<LeftSidebarComponent>;
    let element: HTMLElement;
    let activeOrgId: WritableSignal<number | null>;
    /** What the storage holds: the plugins available in the active organization, sorted by name. */
    let availablePlugins: WritableSignal<AvailablePlugin[]>;
    /** The organization the held list belongs to (`null` before one landed). */
    let loadedOrgId: WritableSignal<number | null>;
    let isSuperadmin: boolean;

    beforeEach(() => {
        activeOrgId = signal<number | null>(1);
        availablePlugins = signal<AvailablePlugin[]>([]);
        loadedOrgId = signal<number | null>(null);
        isSuperadmin = false;
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: AvailablePluginsStorageService, useValue: { plugins: availablePlugins, loadedOrgId } },
                { provide: InteractivityChecker, useClass: LaidOutInteractivityChecker },
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
                        resolveDefaultRoute: () => '/agents',
                        get isSuperadmin(): boolean {
                            return isSuperadmin;
                        },
                    },
                },
                // The account menu lists the tours, as in the app; none is registered here.
                { provide: TOUR_PROGRESS_STORE, useExisting: ProfileTourProgressStore },
                {
                    provide: ConfigService,
                    useValue: { isAuditTrailEnabled: false, isChatEnabled: true, isPluginsEnabled: true },
                },
                {
                    provide: ChatInboxStreamService,
                    useValue: { waitingCount: signal(WAITING_COUNT), start: vi.fn(), stop: vi.fn() },
                },
            ],
        });

        fixture = TestBed.createComponent(LeftSidebarComponent);
        element = fixture.nativeElement as HTMLElement;
    });

    afterEach(() => {
        localStorage.clear();
        sessionStorage.clear();
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

    /** The labels of the top links, in order: the visible text when expanded, the aria-label when collapsed. */
    function topLinkLabels(): string[] {
        return Array.from(element.querySelectorAll<HTMLElement>('.main-nav a.sidenav-nav-link')).map(
            (link) =>
                link.querySelector('.sidenav-row-label')?.textContent?.trim() ?? link.getAttribute('aria-label') ?? ''
        );
    }

    /** What the storage does when a list lands: the list and its organization together. */
    function showPlugins(plugins: AvailablePlugin[]): void {
        availablePlugins.set(plugins);
        loadedOrgId.set(1);
        fixture.detectChanges();
    }

    /** A row that opens a list: by its aria-label (collapsed) or its visible label (expanded). */
    function listRow(label: string): HTMLButtonElement | undefined {
        return Array.from(element.querySelectorAll<HTMLButtonElement>('.sidenav-nav-button')).find(
            (button) =>
                button.getAttribute('aria-label') === label ||
                button.querySelector('.sidenav-row-label')?.textContent?.trim() === label
        );
    }

    function popover(): HTMLElement | null {
        return TestBed.inject(OverlayContainer).getContainerElement().querySelector<HTMLElement>('.apps-popover');
    }

    function appLinks(container: ParentNode): HTMLAnchorElement[] {
        return Array.from(container.querySelectorAll<HTMLAnchorElement>('a.apps-list__item'));
    }

    function hrefs(links: HTMLAnchorElement[]): (string | null)[] {
        return links.map((link) => link.getAttribute('href'));
    }

    async function open(row: HTMLButtonElement): Promise<void> {
        row.click();
        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();
    }

    async function navigate(url: string): Promise<void> {
        await TestBed.inject(Router).navigateByUrl(url);
        fixture.detectChanges();
    }

    /** The rows between the logo and the bottom block, by their visible labels (expanded). */
    function mainLabels(): string[] {
        return Array.from(element.querySelectorAll('.main-nav > li > .tooltip-wrapper .sidenav-row-label')).map(
            (label) => label.textContent!.trim()
        );
    }

    function menuLinks(): HTMLAnchorElement[] {
        return Array.from(element.querySelectorAll<HTMLAnchorElement>('.main-nav a.sidenav-nav-link')).filter(
            (link) => link.querySelector('app-plugin-menu-icon') !== null
        );
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
            expect(navLink('Recycle Bin')!.getAttribute('aria-label')).toBe('Recycle Bin');
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
            expect(labelTexts()).toEqual(expect.arrayContaining(['Agents', 'Flows', 'Recycle Bin', 'Settings']));
            expect(navLink('Agents')!.hasAttribute('aria-label')).toBe(false);
            expect(navLink('Settings')!.hasAttribute('aria-label')).toBe(false);
            expect(navLink('Recycle Bin')!.hasAttribute('aria-label')).toBe(false);
        });

        it('suppresses the hover tooltips', () => {
            hoverItem('Flows');
            hoverItem('Recycle Bin');

            expect(visibleTooltipTexts()).not.toContain('Flows');
            expect(visibleTooltipTexts()).not.toContain('Recycle Bin');
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

        it.each([
            ['Recycle Bin', '/recycle-bin/flows'],
            ['Settings', '/settings'],
        ])('highlights %s on its pages', async (label, url) => {
            expect(navLink(label)!.classList).not.toContain('active');

            await TestBed.inject(Router).navigateByUrl(url);
            fixture.detectChanges();

            expect(navLink(label)!.classList).toContain('active');
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

    describe('Apps row', () => {
        it('replaces the per-plugin rows: one row below a divider, after the fixed items', () => {
            render(EXPANDED_WIDTH);
            showPlugins([ATLAS, WEATHER]);

            expect(topLinkLabels()).toEqual(STATIC_TOP_LABELS);
            expect(element.querySelector('.main-nav a[href^="/plugins/"]')).toBeNull();
            const appsItem = listRow('Apps')!.closest('li')!;
            expect(appsItem.previousElementSibling?.getAttribute('role')).toBe('separator');
            expect(appsItem.nextElementSibling).toBeNull();
        });

        it('is absent, divider and all, when no app is available (platform off, no organization, none granted)', () => {
            render(EXPANDED_WIDTH);

            expect(listRow('Apps')).toBeUndefined();
            expect(element.querySelector('.main-nav [role="separator"]')).toBeNull();
        });

        it('follows the list: gone on an org switch, back when the new list arrives', () => {
            render(EXPANDED_WIDTH);
            showPlugins([WEATHER]);
            expect(listRow('Apps')).toBeDefined();

            showPlugins([]);
            expect(listRow('Apps')).toBeUndefined();

            showPlugins([ATLAS]);
            expect(listRow('Apps')).toBeDefined();
        });

        it('opens a popover of the apps, headed with the organization, focused on the first app', async () => {
            render(EXPANDED_WIDTH);
            showPlugins([ATLAS, WEATHER]);
            const row = listRow('Apps')!;
            expect(row.getAttribute('aria-expanded')).toBe('false');
            expect(row.getAttribute('aria-haspopup')).toBe('dialog');

            await open(row);

            expect(row.getAttribute('aria-expanded')).toBe('true');
            expect(popover()!.getAttribute('role')).toBe('dialog');
            expect(popover()!.getAttribute('aria-label')).toBe('Apps');
            expect(popover()!.querySelector('.apps-list__organization')!.textContent!.trim()).toBe(ORG_NAME);
            expect(hrefs(appLinks(popover()!))).toEqual(['/plugins/atlas', '/plugins/weather']);
            expect(document.activeElement).toBe(appLinks(popover()!)[0]);
        });

        it('focuses the search field when the popover has one', async () => {
            render(EXPANDED_WIDTH);
            showPlugins(
                Array.from({ length: 7 }, (_, index) =>
                    buildAvailablePlugin({ identifier: `app-${index}`, name: `App ${index}` })
                )
            );

            await open(listRow('Apps')!);

            expect(document.activeElement).toBe(popover()!.querySelector('app-search input'));
        });

        it('closes on Escape and gives the focus back to its row', async () => {
            render(EXPANDED_WIDTH);
            showPlugins([ATLAS, WEATHER]);
            const row = listRow('Apps')!;
            await open(row);

            popover()!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            fixture.detectChanges();

            expect(popover()).toBeNull();
            expect(row.getAttribute('aria-expanded')).toBe('false');
            expect(document.activeElement).toBe(row);
        });

        it('closes when the row is pressed again, and when an app is followed', async () => {
            render(EXPANDED_WIDTH);
            showPlugins([ATLAS, WEATHER]);
            await open(listRow('Apps')!);

            await open(listRow('Apps')!);
            expect(popover()).toBeNull();

            await open(listRow('Apps')!);
            appLinks(popover()!)[1].click();
            await fixture.whenStable();
            fixture.detectChanges();

            expect(TestBed.inject(Router).url).toBe('/plugins/weather');
            expect(popover()).toBeNull();
        });

        it.each([
            { superadmin: true, shown: true },
            { superadmin: false, shown: false },
        ])('offers "Manage apps" to a SuperAdmin only ($superadmin)', async ({ superadmin, shown }) => {
            isSuperadmin = superadmin;
            render(EXPANDED_WIDTH);
            showPlugins([WEATHER]);

            await open(listRow('Apps')!);

            const manage = popover()!.querySelector<HTMLAnchorElement>('.apps-list-footer-link');
            expect(manage !== null).toBe(shown);
            if (manage) {
                expect(manage.textContent!.trim()).toBe('Manage apps');
                expect(manage.getAttribute('href')).toBe('/workspace/plugins');
            }
        });

        it('marks a newly granted app: a dot on the row until the list opens, a tag while it is open', async () => {
            render(EXPANDED_WIDTH);
            showPlugins([WEATHER]);
            TestBed.tick();
            showPlugins([ATLAS, WEATHER]);
            const row = listRow('Apps')!;
            expect(row.querySelector('.sidenav-new-dot')).not.toBeNull();
            expect(row.querySelector('.visually-hidden')!.textContent!.trim()).toBe(', new apps available');

            await open(row);

            expect(row.querySelector('.sidenav-new-dot')).toBeNull();
            const tagged = appLinks(popover()!).filter((link) => link.querySelector('.apps-list__new'));
            expect(hrefs(tagged)).toEqual(['/plugins/atlas']);

            await open(row);
            await open(row);
            expect(popover()!.querySelector('.apps-list__new')).toBeNull();
        });

        it('lists the apps inline under the row in the drawer, not in a popover', async () => {
            fixture.componentRef.setInput('inDrawer', true);
            isSuperadmin = true;
            render(EXPANDED_WIDTH);
            showPlugins([ATLAS, WEATHER]);
            const row = listRow('Apps')!;
            expect(row.hasAttribute('aria-haspopup')).toBe(false);

            await open(row);

            expect(popover()).toBeNull();
            const inline = element.querySelector<HTMLElement>('#sidenav-apps-list')!;
            expect(row.getAttribute('aria-controls')).toBe('sidenav-apps-list');
            expect(inline.previousElementSibling).toBe(row.closest('li'));
            expect(hrefs(appLinks(inline))).toEqual(['/plugins/atlas', '/plugins/weather']);
            expect(inline.querySelector('app-search')).toBeNull();
            expect(inline.querySelector('.apps-list-footer-link')!.textContent!.trim()).toBe('Manage apps');
        });

        it('opens a popover from a collapsed drawer, where names do not fit under the row', async () => {
            fixture.componentRef.setInput('inDrawer', true);
            render(COLLAPSED_WIDTH);
            showPlugins([WEATHER]);

            await open(listRow('Apps')!);

            expect(popover()).not.toBeNull();
        });

        it('is an icon named by its aria-label when collapsed, its tooltip hidden while its popover is open', async () => {
            render(COLLAPSED_WIDTH);
            showPlugins([WEATHER]);
            const row = listRow('Apps')!;
            expect(row.getAttribute('aria-label')).toBe('Apps');

            hoverItem('Apps');
            expect(visibleTooltipTexts()).toContain('Apps');

            await open(row);
            expect(visibleTooltipTexts()).not.toContain('Apps');
        });
    });

    describe('in an app', () => {
        async function openApp(url: string, width = EXPANDED_WIDTH): Promise<void> {
            render(width);
            showPlugins([ATLAS, WEATHER]);
            await navigate(url);
        }

        it("swaps EpicStaff's rows for the way back, the app switcher and the app's menu", async () => {
            await openApp('/plugins/atlas/projects/2');

            expect(mainLabels()).toEqual(['Back to EpicStaff', 'Atlas', 'Overview', 'Projects', 'Reports']);
            const separators = element.querySelectorAll('.main-nav > [role="separator"]');
            expect(separators.length).toBe(1);
            expect(separators[0].nextElementSibling!.textContent).toContain('Overview');
        });

        it('leads back to the last EpicStaff page shown in this tab', async () => {
            render(EXPANDED_WIDTH);
            showPlugins([ATLAS]);
            TestBed.inject(AppReturnUrlService).record('/storage/files?folder=7');

            await navigate('/plugins/atlas');

            expect(navLink('Back to EpicStaff')!.getAttribute('href')).toBe('/storage/files?folder=7');
        });

        it("links each menu item to its page in the app, drawn with the item's own icon", async () => {
            await openApp('/plugins/atlas');

            expect(hrefs(menuLinks())).toEqual(['/plugins/atlas', '/plugins/atlas/projects', '/plugins/atlas/reports']);
            expect(
                menuLinks()[1].querySelector<HTMLElement>('app-plugin-menu-icon')!.style.getPropertyValue('mask-image')
            ).toBe('url("/api/plugin-public/atlas/icons/projects.svg/?v=2.0.0")');
        });

        it('marks the item the page belongs to, following every navigation, as one a plugin page makes', async () => {
            await openApp('/plugins/atlas');
            const current = (): [string | null, string | null][] =>
                menuLinks()
                    .filter((link) => link.hasAttribute('aria-current'))
                    .map((link) => [link.getAttribute('href'), link.getAttribute('aria-current')]);
            expect(current()).toEqual([['/plugins/atlas', 'page']]);

            // What the host page does when the page reports `nav.changed`. A page below the item's: not its page.
            await TestBed.inject(Router).navigate(['/plugins', 'atlas', 'projects', '2'], { replaceUrl: true });
            fixture.detectChanges();
            expect(current()).toEqual([['/plugins/atlas/projects', 'true']]);
            expect(menuLinks()[1].classList).toContain('active');

            await navigate('/plugins/atlas/projects?tab=1');
            expect(current()).toEqual([['/plugins/atlas/projects', 'page']]);

            await navigate('/plugins/atlas/settings');
            expect(current()).toEqual([]);
        });

        it('shows no divider and no menu for an app without one', async () => {
            await openApp('/plugins/weather');

            expect(mainLabels()).toEqual(['Back to EpicStaff', 'Weather']);
            expect(element.querySelector('.main-nav [role="separator"]')).toBeNull();
        });

        it('names an app missing from the list by its identifier, with a placeholder icon and no menu', async () => {
            await openApp('/plugins/gone/projects');

            expect(mainLabels()).toEqual(['Back to EpicStaff', 'gone']);
            expect(listRow('gone')!.querySelector('app-plugin-icon .plugin-icon--placeholder')).not.toBeNull();
        });

        it('keeps only the account row at the bottom: no Recycle Bin, no Settings', async () => {
            await openApp('/plugins/atlas');

            expect(navLink('Recycle Bin')).toBeUndefined();
            expect(navLink('Settings')).toBeUndefined();
            expect(accountRow()).not.toBeNull();
        });

        it('switches apps from a popover that checks the current one and opens the page in a new tab', async () => {
            await openApp('/plugins/atlas/projects?tab=1');
            const switcher = listRow('Atlas')!;
            expect(switcher.querySelector('.visually-hidden')!.textContent!.trim()).toBe(', switch app');

            await open(switcher);

            expect(popover()!.getAttribute('aria-label')).toBe('Switch app');
            const links = appLinks(popover()!);
            expect(hrefs(links)).toEqual(['/plugins/atlas', '/plugins/weather']);
            expect(links[0].getAttribute('aria-current')).toBe('true');
            expect(links[1].hasAttribute('aria-current')).toBe(false);
            const newTab = popover()!.querySelector<HTMLAnchorElement>('.apps-list-footer-link')!;
            expect(newTab.textContent!.trim()).toBe('Open in a new tab');
            expect(newTab.getAttribute('href')).toBe('/plugins/atlas/projects?tab=1');
            expect(newTab.getAttribute('target')).toBe('_blank');
            expect(newTab.getAttribute('rel')).toBe('noopener');
        });

        it("goes back to EpicStaff's rows when the address leaves the app", async () => {
            await openApp('/plugins/atlas');

            await navigate('/flows');

            expect(topLinkLabels()).toEqual(STATIC_TOP_LABELS);
            expect(listRow('Apps')).toBeDefined();
            expect(navLink('Back to EpicStaff')).toBeUndefined();
        });

        it('names every row by its aria-label and shows it as a tooltip when collapsed', async () => {
            await openApp('/plugins/atlas', COLLAPSED_WIDTH);

            expect(labelTexts()).toEqual([]);
            expect(navLink('Back to EpicStaff')).toBeDefined();
            expect(listRow('Atlas, switch app')).toBeDefined();
            expect(menuLinks().map((link) => link.getAttribute('aria-label'))).toEqual([
                'Overview',
                'Projects',
                'Reports',
            ]);

            hoverItem('Projects');
            expect(visibleTooltipTexts()).toContain('Projects');

            listRow('Atlas, switch app')!.closest('li')!.dispatchEvent(new MouseEvent('mouseenter'));
            fixture.detectChanges();
            expect(visibleTooltipTexts()).toContain('Atlas, switch app');

            await open(listRow('Atlas, switch app')!);
            expect(visibleTooltipTexts()).not.toContain('Atlas, switch app');
        });
    });
});

@Component({ template: '' })
class StubDialogComponent {}

describe('LeftSidebarComponent page shortcuts', () => {
    let fixture: ComponentFixture<LeftSidebarComponent>;
    let router: Router;
    let hiddenResources: Set<ResourceCode>;
    let leaveFlowAllowed: boolean;
    let workspaceAllowed: boolean;
    let settingsAllowed: boolean;
    let config: { isAuditTrailEnabled: boolean };
    let availablePlugins: WritableSignal<AvailablePlugin[]>;

    beforeEach(() => {
        hiddenResources = new Set();
        leaveFlowAllowed = true;
        workspaceAllowed = true;
        settingsAllowed = true;
        config = { isAuditTrailEnabled: false };
        availablePlugins = signal<AvailablePlugin[]>([]);
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: AvailablePluginsStorageService,
                    useValue: { plugins: availablePlugins, loadedOrgId: signal(1) },
                },
                provideRouter([
                    { path: 'workspace', children: [{ path: 'users', children: [] }] },
                    { path: 'agents', children: [] },
                    { path: 'tools', children: [] },
                    { path: 'venvs', children: [] },
                    { path: 'storage', children: [] },
                    { path: 'flows', children: [] },
                    { path: 'flows/:id', children: [], canDeactivate: [() => leaveFlowAllowed] },
                    { path: 'chats', children: [] },
                    { path: 'audit', children: [] },
                    { path: 'recycle-bin', children: [{ path: 'flows', children: [] }] },
                    { path: 'settings', children: [] },
                    { path: 'profile', children: [{ path: 'overview', children: [] }] },
                    { path: 'plugins', children: [{ path: '**', children: [] }] },
                    { path: 'unlisted', children: [] },
                ]),
                { provide: ProfileService, useValue: { currentUserSignal: signal(USER) } },
                { provide: ActiveOrgService, useValue: { activeOrgId: signal(1) } },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode) => !hiddenResources.has(resource),
                        resolveStorageTab: () => 'files',
                        canOpenConfigureModelsDialog: () => settingsAllowed,
                        canAccessWorkspace: () => workspaceAllowed,
                        resolveDefaultRoute: () => '/agents',
                        isSuperadmin: false,
                    },
                },
                // The account menu lists the tours, as in the app; none is registered here.
                { provide: TOUR_PROGRESS_STORE, useExisting: ProfileTourProgressStore },
                { provide: ConfigService, useValue: config },
            ],
        });

        router = TestBed.inject(Router);
        fixture = TestBed.createComponent(LeftSidebarComponent);
        fixture.componentRef.setInput('width', COLLAPSED_WIDTH);
        fixture.detectChanges();
    });

    afterEach(() => {
        TestBed.inject(Dialog).closeAll();
        document.body.querySelectorAll('[data-test-editable]').forEach((element) => element.remove());
    });

    async function startAt(url: string): Promise<void> {
        await router.navigateByUrl(url);
        fixture.detectChanges();
    }

    async function press(
        code: 'ArrowUp' | 'ArrowDown',
        options: KeyboardEventInit = {},
        target: EventTarget = document.body
    ): Promise<KeyboardEvent> {
        const event = new KeyboardEvent('keydown', {
            code,
            key: code,
            altKey: true,
            bubbles: true,
            cancelable: true,
            ...options,
        });
        target.dispatchEvent(event);
        await fixture.whenStable();
        return event;
    }

    function editable(html: string): HTMLElement {
        const container = document.createElement('div');
        container.setAttribute('data-test-editable', '');
        container.innerHTML = html;
        document.body.appendChild(container);
        return container.querySelector<HTMLElement>('[data-target]')!;
    }

    it.each([
        { start: '/agents', code: 'ArrowDown', expected: '/tools' },
        { start: '/tools', code: 'ArrowUp', expected: '/agents' },
        { start: '/agents', code: 'ArrowUp', expected: '/workspace' },
        { start: '/workspace/users', code: 'ArrowDown', expected: '/agents' },
        { start: '/flows/3', code: 'ArrowDown', expected: '/chats' },
        { start: '/flows/3', code: 'ArrowUp', expected: '/storage' },
        { start: '/chats', code: 'ArrowDown', expected: '/recycle-bin' },
        { start: '/recycle-bin', code: 'ArrowDown', expected: '/settings' },
        { start: '/recycle-bin/flows', code: 'ArrowUp', expected: '/chats' },
        { start: '/settings', code: 'ArrowUp', expected: '/recycle-bin' },
        { start: '/unlisted', code: 'ArrowDown', expected: '/workspace' },
        { start: '/settings', code: 'ArrowDown', expected: '/profile' },
        { start: '/profile/overview', code: 'ArrowUp', expected: '/settings' },
        { start: '/unlisted', code: 'ArrowUp', expected: '/profile' },
        { start: '/workspace', code: 'ArrowUp', expected: '/workspace' },
        { start: '/profile', code: 'ArrowDown', expected: '/profile' },
    ] as const)('Alt+$code from $start goes to $expected', async ({ start, code, expected }) => {
        await startAt(start);

        await press(code);

        expect(router.url).toBe(expected);
    });

    it('prevents the browser default only when it navigates', async () => {
        await startAt('/workspace');

        expect((await press('ArrowUp')).defaultPrevented).toBe(false);
        expect((await press('ArrowDown')).defaultPrevented).toBe(true);
    });

    it('steps from Chats to Audit when the audit trail is shown', async () => {
        config.isAuditTrailEnabled = true;
        await startAt('/chats');

        await press('ArrowDown');

        expect(router.url).toBe('/audit');
    });

    it('steps from Chats to Recycle Bin past the Apps row, which leads to no page', async () => {
        availablePlugins.set([ATLAS, WEATHER]);
        await startAt('/chats');

        await press('ArrowDown');

        expect(router.url).toBe('/recycle-bin');
    });

    it.each(['ArrowDown', 'ArrowUp'] as const)('leaves Alt+%s to the page in an app', async (code) => {
        availablePlugins.set([ATLAS, WEATHER]);
        await startAt('/plugins/atlas/projects');

        const event = await press(code);

        expect(router.url).toBe('/plugins/atlas/projects');
        expect(event.defaultPrevented).toBe(false);
    });

    it.each([
        {
            name: 'Tools',
            hide: () => hiddenResources.add(ResourceCode.Tools),
            start: '/agents',
            code: 'ArrowDown',
            expected: '/venvs',
        },
        {
            name: 'Workspace',
            hide: () => (workspaceAllowed = false),
            start: '/agents',
            code: 'ArrowUp',
            expected: '/agents',
        },
        {
            name: 'Settings',
            hide: () => (settingsAllowed = false),
            start: '/recycle-bin',
            code: 'ArrowDown',
            expected: '/profile',
        },
    ] as const)('skips $name when the user may not see it', async ({ hide, start, code, expected }) => {
        hide();
        await startAt(start);

        await press(code);

        expect(router.url).toBe(expected);
    });

    it('goes through the router guards, so a flow with unsaved changes is not left', async () => {
        leaveFlowAllowed = false;
        await startAt('/flows/3');

        await press('ArrowDown');

        expect(router.url).toBe('/flows/3');
    });

    it.each([
        { name: 'Ctrl', options: { ctrlKey: true } },
        { name: 'Shift', options: { shiftKey: true } },
        { name: 'Meta', options: { metaKey: true } },
        { name: 'no Alt', options: { altKey: false } },
        { name: 'a held-down key', options: { repeat: true } },
    ])('ignores the key with $name', async ({ options }) => {
        await startAt('/agents');

        const event = await press('ArrowDown', options);

        expect(router.url).toBe('/agents');
        expect(event.defaultPrevented).toBe(false);
    });

    it.each([
        { name: 'an input', html: '<input data-target />' },
        { name: 'a textarea', html: '<textarea data-target></textarea>' },
        { name: 'a select', html: '<select data-target></select>' },
        { name: 'a contenteditable element', html: '<div contenteditable="true"><span data-target></span></div>' },
        { name: 'the code editor', html: '<div class="monaco-editor"><div data-target></div></div>' },
    ])('ignores the key while typing in $name', async ({ html }) => {
        await startAt('/agents');

        await press('ArrowDown', {}, editable(html));

        expect(router.url).toBe('/agents');
    });

    it('leaves a key another control already handled, such as a grid opening its menu', async () => {
        await startAt('/agents');
        const control = editable('<div data-target></div>');
        control.addEventListener('keydown', (event) => event.preventDefault());

        await press('ArrowDown', {}, control);

        expect(router.url).toBe('/agents');
    });

    it('closes the account menu when it moves to another page', async () => {
        await startAt('/agents');
        fixture.nativeElement.querySelector('.user-avatar-btn').click();
        fixture.detectChanges();
        expect(fixture.nativeElement.querySelector('app-user-menu')).not.toBeNull();

        await press('ArrowDown');
        fixture.detectChanges();

        expect(router.url).toBe('/tools');
        expect(fixture.nativeElement.querySelector('app-user-menu')).toBeNull();
    });

    it('ignores the key while a dialog is open', async () => {
        await startAt('/agents');
        TestBed.inject(Dialog).open(StubDialogComponent);

        await press('ArrowDown');

        expect(router.url).toBe('/agents');
    });
});
