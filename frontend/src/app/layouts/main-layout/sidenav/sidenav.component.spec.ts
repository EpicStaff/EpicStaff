import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter, Router } from '@angular/router';
import { GetMeResponse, ResourceCode } from '@shared/models';

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
                        canApplyQuickstart: () => false,
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

    beforeEach(() => {
        hiddenResources = new Set();
        leaveFlowAllowed = true;
        workspaceAllowed = true;
        settingsAllowed = true;
        config = { isAuditTrailEnabled: false };
        TestBed.configureTestingModule({
            providers: [
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
                        canApplyQuickstart: () => false,
                        canAccessWorkspace: () => workspaceAllowed,
                    },
                },
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
