import { Component, signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { of, Subject } from 'rxjs';

import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { AvailablePlugin } from '../../models/available-plugin.model';
import { PluginTheme } from '../../models/plugin-frame-protocol.model';
import { AvailablePluginsStorageService } from '../../services/available-plugins-storage.service';
import { PluginHostThemeService } from '../../services/plugin-host-theme.service';
import { buildAvailablePlugin } from '../../testing/plugin-fixtures';
import { FakeMessageChannel, FakeMessagePort, postFromWindow } from '../../testing/plugin-frame-test-harness';
import { PluginHostPageComponent } from './plugin-host-page.component';
import { pluginPageMatcher } from './plugin-page.matcher';

const FRAME_ORIGIN = 'https://weather.plugins.example.com';
const ATLAS_ORIGIN = 'https://atlas.plugins.example.com';
const SANDBOX =
    'allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads allow-modals';

@Component({ template: '' })
class SlowPageComponent {}

describe('PluginHostPageComponent', () => {
    let harness: RouterTestingHarness;
    let plugins: WritableSignal<AvailablePlugin[]>;
    let posted: { message: unknown; targetOrigin: string; transfer: unknown[] }[];
    /** Holds a navigation to `/slow` in its guard until the test answers. */
    let slowGate: Subject<boolean>;
    let slowGuardEntered: boolean;
    const refresh = vi.fn(() => of<AvailablePlugin[]>([]));

    beforeEach(async () => {
        vi.stubGlobal('MessageChannel', FakeMessageChannel);
        // The message view's button collapses on overflow, measured with a ResizeObserver; jsdom has none.
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );
        plugins = signal([
            buildAvailablePlugin(),
            buildAvailablePlugin({ identifier: 'atlas', name: 'Atlas', frame_origin: ATLAS_ORIGIN }),
        ]);
        posted = [];
        slowGate = new Subject<boolean>();
        slowGuardEntered = false;
        refresh.mockClear();
        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    { matcher: pluginPageMatcher, component: PluginHostPageComponent },
                    {
                        path: 'slow',
                        canActivate: [
                            () => {
                                slowGuardEntered = true;
                                return slowGate;
                            },
                        ],
                        component: SlowPageComponent,
                    },
                ]),
                { provide: AvailablePluginsStorageService, useValue: { plugins, refresh } },
                { provide: ActiveOrgService, useValue: { activeOrgId: signal(3) } },
                {
                    provide: ProfileService,
                    useValue: {
                        currentUserSignal: signal({ memberships: [{ organization: { id: 3, name: 'Acme' } }] }),
                    },
                },
                {
                    provide: PluginHostThemeService,
                    useValue: { theme: signal<PluginTheme>({ mode: 'dark', tokens: {} }) },
                },
            ],
        });
        harness = await RouterTestingHarness.create();
    });

    afterEach(() => vi.unstubAllGlobals());

    function frame(): HTMLIFrameElement | null {
        return (harness.routeNativeElement as HTMLElement | null)?.querySelector('iframe') ?? null;
    }

    /** The frame now shown, with what EpicStaff posts to its window recorded in `posted`. */
    function currentFrame(): HTMLIFrameElement {
        const iframe = frame();
        if (!iframe?.contentWindow) throw new Error('no frame');
        iframe.contentWindow.postMessage = ((message: unknown, targetOrigin: string, transfer: unknown[] = []) =>
            posted.push({ message, targetOrigin, transfer })) as unknown as Window['postMessage'];
        return iframe;
    }

    async function open(url: string): Promise<HTMLIFrameElement> {
        await harness.navigateByUrl(url);
        harness.detectChanges();
        return currentFrame();
    }

    /** Lets the router and the host page finish what a navigation started (including follow-up navigations). */
    async function settle(): Promise<void> {
        await new Promise((resolve) => setTimeout(resolve));
        await harness.fixture.whenStable();
        harness.detectChanges();
    }

    /**
     * Starts a user navigation to `/slow` and waits until it is held in its guard. The navigation's promise comes back
     * wrapped: an async function returning it bare would wait for the navigation itself.
     */
    async function startSlowNavigation(): Promise<{ settled: Promise<boolean> }> {
        const settled = TestBed.inject(Router).navigateByUrl('/slow');
        while (!slowGuardEntered) await new Promise((resolve) => setTimeout(resolve));
        return { settled };
    }

    function handshake(iframe: HTMLIFrameElement, origin = FRAME_ORIGIN): FakeMessagePort {
        postFromWindow(iframe.contentWindow, { type: 'es:ready', protocol: 1 }, origin);
        const port = posted.at(-1)?.transfer[0];
        if (!(port instanceof FakeMessagePort)) throw new Error('no port was transferred');
        return port;
    }

    it('frames the plugin origin at the page path with es_org, in the sandbox the plan pins', async () => {
        const iframe = await open('/plugins/weather/forecast?city=Berlin');

        expect(iframe.getAttribute('src')).toBe(`${FRAME_ORIGIN}/forecast?city=Berlin&es_org=3`);
        expect(iframe.getAttribute('sandbox')).toBe(SANDBOX);
        expect(iframe.getAttribute('referrerpolicy')).toBe('strict-origin');
        expect(iframe.getAttribute('allow')).toBe('clipboard-write');
        expect(iframe.title).toBe('Weather');
    });

    it('answers the handshake with the page path and the organization', async () => {
        const iframe = await open('/plugins/weather/forecast?city=Berlin');

        handshake(iframe);

        expect(posted[0].targetOrigin).toBe(FRAME_ORIGIN);
        expect(posted[0].message).toMatchObject({
            type: 'es:init',
            nav: { path: '/forecast?city=Berlin' },
            org: { id: 3, name: 'Acme' },
        });
    });

    it('moves the address when the page navigates, without reloading the frame', async () => {
        const iframe = await open('/plugins/weather');
        const port = handshake(iframe);

        port.postMessage({ type: 'nav.changed', path: '/about', replace: false });
        await harness.fixture.whenStable();
        harness.detectChanges();

        expect(TestBed.inject(Router).url).toBe('/plugins/weather/about');
        expect(frame()).toBe(iframe);
        expect(iframe.getAttribute('src')).toBe(`${FRAME_ORIGIN}/?es_org=3`);
        expect(port.received).toEqual([]);
    });

    it('tells the page about an address change made in EpicStaff, keeping the same frame', async () => {
        const iframe = await open('/plugins/weather');
        const port = handshake(iframe);

        await harness.navigateByUrl('/plugins/weather/forecast?city=Rome');
        harness.detectChanges();

        expect(port.received).toEqual([{ type: 'nav.navigate', path: '/forecast?city=Rome' }]);
        expect(frame()).toBe(iframe);
    });

    it('never sends another plugin’s address to the frame still attached', async () => {
        const weatherPort = handshake(await open('/plugins/weather/forecast'));

        await harness.navigateByUrl('/plugins/atlas/customers/42?tab=billing');
        harness.detectChanges();

        expect(weatherPort.received).toEqual([]);
        expect(weatherPort.partner?.closed).toBe(true);
        handshake(currentFrame(), ATLAS_ORIGIN);
        expect(posted.at(-1)).toMatchObject({
            targetOrigin: ATLAS_ORIGIN,
            message: { type: 'es:init', nav: { path: '/customers/42?tab=billing' } },
        });
    });

    it('lets a navigation the user started win over a nav.changed that arrives meanwhile', async () => {
        const port = handshake(await open('/plugins/weather'));
        const router = TestBed.inject(Router);

        const userNavigation = await startSlowNavigation();
        port.postMessage({ type: 'nav.changed', path: '/about', replace: false });
        slowGate.next(true);
        await userNavigation.settled;
        await settle();

        expect(router.url).toBe('/slow');
    });

    it("brings the address to the page's path when the user's navigation is cancelled", async () => {
        const port = handshake(await open('/plugins/weather'));
        const router = TestBed.inject(Router);

        const userNavigation = await startSlowNavigation();
        port.postMessage({ type: 'nav.changed', path: '/about', replace: false });
        slowGate.next(false);
        await userNavigation.settled;
        await settle();

        expect(router.url).toBe('/plugins/weather/about');
        expect(port.received).toEqual([]);
    });

    it('Try again reloads the available plugins, and the page opens once its plugin is there', async () => {
        plugins.set([]);
        await harness.navigateByUrl('/plugins/weather');
        harness.detectChanges();
        expect(frame()).toBeNull();

        const tryAgain = Array.from(
            (harness.routeNativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('button')
        ).find((button) => button.textContent?.trim() === 'Try again');
        tryAgain?.click();
        plugins.set([buildAvailablePlugin()]);
        harness.detectChanges();

        expect(refresh).toHaveBeenCalledTimes(1);
        expect(frame()?.getAttribute('src')).toBe(`${FRAME_ORIGIN}/?es_org=3`);
    });

    it('opens a new frame for another plugin', async () => {
        const weatherFrame = await open('/plugins/weather');

        await harness.navigateByUrl('/plugins/atlas');
        harness.detectChanges();

        expect(frame()).not.toBe(weatherFrame);
        expect(frame()?.getAttribute('src')).toBe(`${ATLAS_ORIGIN}/?es_org=3`);
    });

    it('frames nothing for a plugin that is not available, or whose origin is not safe', async () => {
        await harness.navigateByUrl('/plugins/chat');
        harness.detectChanges();
        expect(frame()).toBeNull();
        expect(harness.routeNativeElement?.textContent).toContain('Plugin not available');
        expect(refresh).not.toHaveBeenCalled();

        plugins.set([buildAvailablePlugin({ frame_origin: 'http://weather.plugins.example.com' })]);
        await harness.navigateByUrl('/plugins/weather');
        harness.detectChanges();
        expect(frame()).toBeNull();
        expect(harness.routeNativeElement?.textContent).toContain("Couldn't open the plugin");
    });
});
