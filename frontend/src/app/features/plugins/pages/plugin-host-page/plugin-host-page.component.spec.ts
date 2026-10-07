import { Location } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { provideLocationMocks, SpyLocation } from '@angular/common/testing';
import { Component, signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { DomSanitizer } from '@angular/platform-browser';
import { provideRouter, Router, withComponentInputBinding } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { Observable, of, Subject, throwError } from 'rxjs';

import {
    PluginBridgeAttachOptions,
    PluginBridgeHost,
    PluginBridgeStopReason,
} from '../../bridge/plugin-bridge-host.service';
import { buildUiSession, buildUiSessionV2 } from '../../bridge/testing/bridge-test-harness';
import { PluginUiSession } from '../../models/plugin.model';
import { PluginsApiService } from '../../services/plugins-api.service';
import { PluginsStoreService } from '../../services/plugins-store.service';
import { PluginHostPageComponent } from './plugin-host-page.component';
import { pluginPageMatcher } from './plugin-page.matcher';

// jsdom has no ResizeObserver; the overflow directive inside the error state's button only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

type AttachCall = [HTMLIFrameElement, PluginUiSession, PluginBridgeAttachOptions | undefined];

@Component({ template: 'slow page' })
class SlowPageComponent {}

@Component({ template: 'not found' })
class NotFoundPageComponent {}

let slowGuard: Promise<boolean> = Promise.resolve(true);

describe('PluginHostPageComponent', () => {
    let harness: RouterTestingHarness;
    let createUiSession: ReturnType<typeof vi.fn<(id: number) => Observable<PluginUiSession>>>;
    let refreshNav: ReturnType<typeof vi.fn<() => void>>;
    let bridge: {
        attach: ReturnType<typeof vi.fn<(...args: AttachCall) => void>>;
        detach: ReturnType<typeof vi.fn>;
        onFrameLoad: ReturnType<typeof vi.fn>;
        notifyNavigation: ReturnType<typeof vi.fn<(path: string) => void>>;
        stopped: WritableSignal<PluginBridgeStopReason | null>;
    };

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        createUiSession = vi.fn<(id: number) => Observable<PluginUiSession>>();
        refreshNav = vi.fn<() => void>();
        bridge = {
            attach: vi.fn<(...args: AttachCall) => void>(),
            detach: vi.fn(),
            onFrameLoad: vi.fn(),
            notifyNavigation: vi.fn<(path: string) => void>(),
            stopped: signal<PluginBridgeStopReason | null>(null),
        };
        TestBed.configureTestingModule({
            providers: [
                provideRouter(
                    [
                        { matcher: pluginPageMatcher, component: PluginHostPageComponent },
                        // A route that takes a moment to activate, like a lazy page loading its chunk.
                        { path: 'slow', canActivate: [() => slowGuard], component: SlowPageComponent },
                        { path: '**', component: NotFoundPageComponent },
                    ],
                    withComponentInputBinding()
                ),
                provideLocationMocks(),
                { provide: PluginsApiService, useValue: { createUiSession } },
                { provide: PluginsStoreService, useValue: { refreshNav } },
            ],
        });
        TestBed.overrideComponent(PluginHostPageComponent, {
            set: { providers: [{ provide: PluginBridgeHost, useValue: bridge }] },
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    async function open(url = '/plugins/7'): Promise<HTMLElement> {
        harness = await RouterTestingHarness.create();
        await harness.navigateByUrl(url, PluginHostPageComponent);
        return settle();
    }

    async function navigate(url: string): Promise<HTMLElement> {
        await harness.navigateByUrl(url);
        return settle();
    }

    async function settle(): Promise<HTMLElement> {
        await harness.fixture.whenStable();
        harness.detectChanges();
        return harness.routeNativeElement as HTMLElement;
    }

    function lastAttachOptions(): PluginBridgeAttachOptions {
        const options = bridge.attach.mock.calls.at(-1)?.[2];
        if (!options) throw new Error('the bridge was not attached');
        return options;
    }

    function urlChanges(): string[] {
        return (TestBed.inject(Location) as SpyLocation).urlChanges;
    }

    /** Lets a router navigation started from a callback (not awaited by the harness) finish. */
    async function settleNavigation(): Promise<HTMLElement> {
        await new Promise((resolve) => setTimeout(resolve));
        return settle();
    }

    /** Starts a navigation to `/slow` whose guard waits for `decide`, like a lazy page still loading. */
    function startSlowNavigation(): { leaving: Promise<unknown>; decide: (allowed: boolean) => void } {
        let decide: (allowed: boolean) => void = () => undefined;
        slowGuard = new Promise<boolean>((resolve) => (decide = resolve));
        return { leaving: harness.navigateByUrl('/slow'), decide: (allowed) => decide(allowed) };
    }

    describe('opening a page', () => {
        it('renders the page in an iframe with literal sandbox, referrer and permission attributes', async () => {
            const trust = vi.spyOn(TestBed.inject(DomSanitizer), 'bypassSecurityTrustResourceUrl');
            createUiSession.mockReturnValue(of(buildUiSession()));

            const element = await open();
            const frame = element.querySelector('iframe');

            expect(createUiSession).toHaveBeenCalledWith(7);
            expect(frame?.getAttribute('sandbox')).toBe('allow-scripts');
            expect(frame?.getAttribute('referrerpolicy')).toBe('no-referrer');
            expect(frame?.getAttribute('allow')).toBe("camera 'none'; microphone 'none'; geolocation 'none'");
            // A bridge v1 page gets its URL as is: no path fragment.
            expect(frame?.getAttribute('src')).toBe('/api/plugin-ui/token-1/index.html');
            expect(bridge.attach).toHaveBeenCalledWith(
                frame,
                expect.objectContaining({ token: 'token-1' }),
                expect.objectContaining({ devMode: false })
            );
            expect(trust).not.toHaveBeenCalled();
        });

        it('attaches the bridge before the iframe gets its address', async () => {
            let srcAtAttach: string | null = 'not attached';
            bridge.attach.mockImplementation((frame) => {
                srcAtAttach = frame.getAttribute('src');
            });
            createUiSession.mockReturnValue(of(buildUiSession()));

            const element = await open();

            expect(srcAtAttach).toBeNull();
            expect(element.querySelector('iframe')?.getAttribute('src')).toBe('/api/plugin-ui/token-1/index.html');
        });

        it('shows a loading state until the ui-session answers', async () => {
            createUiSession.mockReturnValue(new Subject<PluginUiSession>());

            const element = await open();

            expect(element.querySelector('app-loading-spinner')).not.toBeNull();
            expect(element.querySelector('iframe')).toBeNull();
        });

        it('refuses a URL outside /api/plugin-ui/ and never trusts it', async () => {
            const trust = vi.spyOn(TestBed.inject(DomSanitizer), 'bypassSecurityTrustResourceUrl');
            createUiSession.mockReturnValue(of(buildUiSession({ url: 'https://evil.example/index.html' })));

            const element = await open();

            expect(element.querySelector('iframe')).toBeNull();
            expect(element.textContent).toContain("Couldn't open the plugin");
            expect(trust).not.toHaveBeenCalled();
            expect(bridge.attach).not.toHaveBeenCalled();
        });

        it('explains a suspended plugin and refreshes the navigation buttons', async () => {
            createUiSession.mockReturnValue(
                throwError(
                    () =>
                        new HttpErrorResponse({
                            status: 409,
                            error: { status_code: 409, code: 'plugin_suspended', message: 'An admin suspended it.' },
                        })
                )
            );

            const element = await open();

            expect(element.querySelector('iframe')).toBeNull();
            expect(element.textContent).toContain('This plugin is suspended');
            expect(element.textContent).toContain('An admin suspended it.');
            expect(refreshNav).toHaveBeenCalled();
        });

        it('never opens the plugin a matrix param names instead of the one in the address', async () => {
            createUiSession.mockReturnValue(of(buildUiSession()));
            harness = await RouterTestingHarness.create();

            const routed = await harness.navigateByUrl('/plugins/7/conversations;id=9');

            expect(routed).toBeInstanceOf(NotFoundPageComponent);
            expect(createUiSession).not.toHaveBeenCalled();
        });

        it('leaves the page for an address of the same plugin with a matrix param', async () => {
            createUiSession.mockReturnValue(of(buildUiSessionV2()));
            await open('/plugins/8/conversations');

            await navigate('/plugins/8;id=9/conversations');

            expect(harness.routeDebugElement?.componentInstance).toBeInstanceOf(NotFoundPageComponent);
            expect(createUiSession.mock.calls).toEqual([[8]]);
        });

        it('does not ask for a session for an id that is not a positive integer', async () => {
            const element = await open('/plugins/abc');

            expect(createUiSession).not.toHaveBeenCalled();
            expect(element.textContent).toContain('Plugin not found');
        });

        it('drops the iframe and says why when the bridge stops the page', async () => {
            createUiSession.mockReturnValue(of(buildUiSession()));
            await open();

            bridge.stopped.set('navigated');
            const element = await settle();

            expect(element.querySelector('iframe')).toBeNull();
            expect(element.textContent).toContain('Plugin page stopped');
        });
    });

    describe('deep links (bridge v2)', () => {
        beforeEach(() => createUiSession.mockReturnValue(of(buildUiSessionV2())));

        it('opens the page at the path below /plugins/<id>: in the URL fragment and for init', async () => {
            const element = await open('/plugins/8/conversations/c_1?sort=-updated_at');

            expect(element.querySelector('iframe')?.getAttribute('src')).toBe(
                '/api/plugin-ui/token-1/index.html#/conversations/c_1?sort=-updated_at'
            );
            expect(lastAttachOptions()).toMatchObject({
                initialPath: '/conversations/c_1?sort=-updated_at',
                devMode: false,
            });
        });

        it('opens at / when the address names nothing below the plugin', async () => {
            const element = await open('/plugins/8');

            expect(element.querySelector('iframe')?.getAttribute('src')).toBe('/api/plugin-ui/token-1/index.html#/');
            expect(lastAttachOptions().initialPath).toBe('/');
        });

        it('follows nav.changed in the address bar, without reloading the iframe or echoing it back', async () => {
            const element = await open('/plugins/8/conversations');
            const frame = element.querySelector('iframe');

            lastAttachOptions().onNavChanged?.('/conversations/c_1', false);
            await settle();
            lastAttachOptions().onNavChanged?.('/conversations/c_1?tab=raw%20json', true);
            await settle();

            expect(TestBed.inject(Router).url).toBe('/plugins/8/conversations/c_1?tab=raw%20json');
            expect(urlChanges().slice(-2)).toEqual([
                '/plugins/8/conversations/c_1',
                'replace: /plugins/8/conversations/c_1?tab=raw%20json',
            ]);
            expect(createUiSession).toHaveBeenCalledTimes(1);
            expect(bridge.attach).toHaveBeenCalledTimes(1);
            expect(element.querySelector('iframe')).toBe(frame);
            expect(frame?.getAttribute('src')).toBe('/api/plugin-ui/token-1/index.html#/conversations');
            expect(bridge.notifyNavigation).not.toHaveBeenCalled();
        });

        it('does not navigate when the page reports the path the address already shows', async () => {
            await open('/plugins/8/conversations');
            const changes = urlChanges().length;

            lastAttachOptions().onNavChanged?.('/conversations', false);
            await settle();

            expect(urlChanges()).toHaveLength(changes);
        });

        it('tells the page about an address change made in EpicStaff, such as a sidenav click', async () => {
            await open('/plugins/8/conversations/c_1');

            await navigate('/plugins/8/about?x=a%20b');
            await navigate('/plugins/8');

            expect(bridge.notifyNavigation.mock.calls).toEqual([['/about?x=a%20b'], ['/']]);
            expect(createUiSession).toHaveBeenCalledTimes(1);
            expect(bridge.attach).toHaveBeenCalledTimes(1);
        });

        it('tells the page when the user goes back to where it was', async () => {
            // Done by the app's initial navigation, which TestBed never runs.
            TestBed.inject(Router).setUpLocationChangeListener();
            await open('/plugins/8/conversations');
            lastAttachOptions().onNavChanged?.('/conversations/c_1', false);
            await settle();

            TestBed.inject(Location).back();
            // The router handles popstate in a timer task.
            await new Promise((resolve) => setTimeout(resolve));
            await settle();

            expect(TestBed.inject(Router).url).toBe('/plugins/8/conversations');
            expect(bridge.notifyNavigation.mock.calls).toEqual([['/conversations']]);
        });

        it('reopens for another plugin instead of telling the open page its path', async () => {
            await open('/plugins/8/conversations');
            createUiSession.mockReturnValue(of(buildUiSessionV2({ plugin: { ...buildUiSessionV2().plugin, id: 9 } })));

            await navigate('/plugins/9/settings');

            expect(createUiSession.mock.calls).toEqual([[8], [9]]);
            expect(bridge.notifyNavigation).not.toHaveBeenCalled();
            expect(lastAttachOptions().initialPath).toBe('/settings');
        });

        it('lets a navigation the user started win over a report from the page', async () => {
            await open('/plugins/8/conversations');
            const { leaving, decide } = startSlowNavigation();

            await Promise.resolve();
            lastAttachOptions().onNavChanged?.('/conversations/c_1', false);
            decide(true);
            await leaving;
            await settleNavigation();

            expect(TestBed.inject(Router).url).toBe('/slow');
        });

        it('brings the address to the page path when that navigation is then cancelled', async () => {
            await open('/plugins/8/conversations');
            const { leaving, decide } = startSlowNavigation();

            await Promise.resolve();
            lastAttachOptions().onNavChanged?.('/conversations/c_1', false);
            decide(false);
            await leaving;
            await settleNavigation();

            expect(TestBed.inject(Router).url).toBe('/plugins/8/conversations/c_1');
            expect(urlChanges().at(-1)).toBe('/plugins/8/conversations/c_1');
            expect(bridge.notifyNavigation).not.toHaveBeenCalled();
            expect(createUiSession).toHaveBeenCalledTimes(1);
        });

        it('leaves the address alone after a cancelled navigation when it already shows the page path', async () => {
            await open('/plugins/8/conversations');
            const changes = urlChanges().length;
            const { leaving, decide } = startSlowNavigation();

            decide(false);
            await leaving;
            await settleNavigation();

            expect(TestBed.inject(Router).url).toBe('/plugins/8/conversations');
            expect(urlChanges()).toHaveLength(changes);
        });

        it('ends on the last path the page reported, even when it bounces straight back', async () => {
            await open('/plugins/8/conversations');
            const report = lastAttachOptions().onNavChanged;

            report?.('/conversations/c_1', false);
            report?.('/conversations', false);
            await settleNavigation();

            expect(TestBed.inject(Router).url).toBe('/plugins/8/conversations');
            expect(bridge.notifyNavigation).not.toHaveBeenCalled();
        });

        it('ignores a report from a page EpicStaff is already leaving', async () => {
            await open('/plugins/8/conversations');
            const staleReport = lastAttachOptions().onNavChanged;
            createUiSession.mockReturnValue(new Subject<PluginUiSession>());
            await navigate('/plugins/9');

            staleReport?.('/conversations/c_1', false);
            await settle();

            expect(TestBed.inject(Router).url).toBe('/plugins/9');
        });
    });

    describe('dev mode', () => {
        const devSession = (overrides: Partial<PluginUiSession> = {}): PluginUiSession =>
            buildUiSessionV2({
                url: 'http://localhost:4300/',
                token: '',
                expires_in: null,
                dev_mode: true,
                ...overrides,
            });

        it('loads the dev server in the same sandbox, with a DEV banner only for this user', async () => {
            createUiSession.mockReturnValue(of(devSession()));

            const element = await open('/plugins/8/conversations');
            const frame = element.querySelector('iframe');

            expect(frame?.getAttribute('src')).toBe('http://localhost:4300/#/conversations');
            expect(frame?.getAttribute('sandbox')).toBe('allow-scripts');
            expect(frame?.getAttribute('referrerpolicy')).toBe('no-referrer');
            expect(lastAttachOptions().devMode).toBe(true);
            const banner = element.querySelector('.plugin-host__dev-banner');
            expect(banner?.textContent).toContain('DEV');
            expect(banner?.textContent).toContain('http://localhost:4300/');
            expect(banner?.textContent).toContain('only you see this');
            expect(banner?.textContent).toContain(
                'any page loaded in this frame gets the bridge with your permissions'
            );
        });

        it('reloads the page from the banner with a fresh session, at the current path', async () => {
            createUiSession.mockReturnValue(of(devSession()));
            const element = await open('/plugins/8/conversations');
            lastAttachOptions().onNavChanged?.('/about', false);
            await settle();

            const reloadButton = [...element.querySelectorAll('.plugin-host__dev-banner button')].find((button) =>
                button.textContent?.includes('Reload')
            );
            (reloadButton as HTMLButtonElement | undefined)?.click();
            const reloaded = await settle();

            expect(createUiSession).toHaveBeenCalledTimes(2);
            expect(reloaded.querySelector('iframe')?.getAttribute('src')).toBe('http://localhost:4300/#/about');
        });

        it.each([
            ['https', 'https://localhost:4300/'],
            ['another host', 'http://evil.example/'],
            ['a lookalike host', 'http://localhost.evil.com/'],
            ['user info', 'http://localhost:4300@evil.example/'],
            ['a production path', '/api/plugin-ui/token-1/index.html'],
        ])('refuses a dev URL with %s', async (_label, url) => {
            createUiSession.mockReturnValue(of(devSession({ url })));

            const element = await open('/plugins/8');

            expect(element.querySelector('iframe')).toBeNull();
            expect(element.textContent).toContain("Couldn't open the plugin");
            expect(bridge.attach).not.toHaveBeenCalled();
        });

        it('refuses a localhost URL in production', async () => {
            createUiSession.mockReturnValue(of(buildUiSessionV2({ url: 'http://localhost:4300/' })));

            const element = await open('/plugins/8');

            expect(element.querySelector('iframe')).toBeNull();
            expect(element.querySelector('.plugin-host__dev-banner')).toBeNull();
        });

        it('shows no banner in production', async () => {
            createUiSession.mockReturnValue(of(buildUiSessionV2()));

            const element = await open('/plugins/8');

            expect(element.querySelector('iframe')).not.toBeNull();
            expect(element.querySelector('.plugin-host__dev-banner')).toBeNull();
            expect(lastAttachOptions().devMode).toBe(false);
        });
    });
});
