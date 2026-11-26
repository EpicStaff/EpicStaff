import { Component, signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { of, Subject, tap } from 'rxjs';

import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { AvailablePlugin, AvailablePluginAvailability } from '../../models/available-plugin.model';
import { PluginTheme } from '../../models/plugin-frame-protocol.model';
import { AvailablePluginsStorageService } from '../../services/available-plugins-storage.service';
import { PluginHostThemeService } from '../../services/plugin-host-theme.service';
import { buildAvailablePlugin } from '../../testing/plugin-fixtures';
import { FakeMessageChannel, FakeMessagePort, postFromWindow } from '../../testing/plugin-frame-test-harness';
import {
    PLUGIN_AVAILABILITY_CHECK_MS,
    PLUGIN_MAINTENANCE_POLL_MS,
    PluginHostPageComponent,
} from './plugin-host-page.component';
import { pluginPageMatcher } from './plugin-page.matcher';

const FRAME_ORIGIN = 'https://weather.plugins.example.com';
// A flat host (`{id}-app.example.com`), as most deployments name their plugins.
const ATLAS_ORIGIN = 'https://atlas-app.example.com';
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

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    function frame(): HTMLIFrameElement | null {
        return (harness.routeNativeElement as HTMLElement | null)?.querySelector('iframe') ?? null;
    }

    function tryAgainButton(): HTMLButtonElement {
        const button = Array.from(
            (harness.routeNativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('button')
        ).find((candidate) => candidate.textContent?.trim() === 'Try again');
        if (!button) throw new Error('no Try again button');
        return button;
    }

    /** The next refresh answers only when the test says so, and lands its list as the real storage does. */
    function holdNextRefresh(): Subject<AvailablePlugin[]> {
        const response = new Subject<AvailablePlugin[]>();
        refresh.mockImplementationOnce(() => response.pipe(tap((list) => plugins.set(list))));
        return response;
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

        // Once when the plugin opened, then for Try again.
        expect(refresh).toHaveBeenCalledTimes(1);
        const response = holdNextRefresh();
        tryAgainButton().click();
        response.next([buildAvailablePlugin()]);
        response.complete();
        harness.detectChanges();

        expect(refresh).toHaveBeenCalledTimes(2);
        expect(frame()?.getAttribute('src')).toBe(`${FRAME_ORIGIN}/?es_org=3`);
    });

    it('loads the available plugins again in the background whenever another plugin opens', async () => {
        await open('/plugins/weather');
        expect(refresh).toHaveBeenCalledTimes(1);

        await harness.navigateByUrl('/plugins/weather/about');
        harness.detectChanges();
        expect(refresh).toHaveBeenCalledTimes(1);

        await harness.navigateByUrl('/plugins/atlas');
        harness.detectChanges();
        expect(refresh).toHaveBeenCalledTimes(2);
    });

    describe('while the plugin is served from a developer’s machine', () => {
        function banner(): string | null {
            return (
                (harness.routeNativeElement as HTMLElement | null)
                    ?.querySelector('.plugin-host__development')
                    ?.textContent?.trim() ?? null
            );
        }

        it('says so above the frame, and frames the same address', async () => {
            plugins.set([buildAvailablePlugin({ development: true })]);
            const iframe = await open('/plugins/weather/forecast?city=Berlin');

            expect(banner()).toBe("Development: this plugin is served from a developer's machine.");
            expect(iframe.getAttribute('src')).toBe(`${FRAME_ORIGIN}/forecast?city=Berlin&es_org=3`);
        });

        it('shows no banner for a plugin that is not in development', async () => {
            await open('/plugins/weather');

            expect(banner()).toBeNull();
        });

        it('keeps the frame when development starts or stops', async () => {
            const iframe = await open('/plugins/weather');

            plugins.set([buildAvailablePlugin({ development: true })]);
            harness.detectChanges();
            expect(banner()).not.toBeNull();
            expect(frame()).toBe(iframe);

            plugins.set([buildAvailablePlugin({ development: false })]);
            harness.detectChanges();
            expect(banner()).toBeNull();
            expect(frame()).toBe(iframe);
            expect(iframe.getAttribute('src')).toBe(`${FRAME_ORIGIN}/?es_org=3`);
        });

        it('shows no banner without the frame', async () => {
            plugins.set([buildAvailablePlugin({ development: true, availability: 'maintenance' })]);
            await harness.navigateByUrl('/plugins/weather');
            harness.detectChanges();

            expect(frame()).toBeNull();
            expect(banner()).toBeNull();
        });
    });

    it('opens a new frame for another plugin', async () => {
        const weatherFrame = await open('/plugins/weather');

        await harness.navigateByUrl('/plugins/atlas');
        harness.detectChanges();

        expect(frame()).not.toBe(weatherFrame);
        expect(frame()?.getAttribute('src')).toBe(`${ATLAS_ORIGIN}/?es_org=3`);
    });

    describe('while the plugin is being updated', () => {
        function text(): string {
            return (harness.routeNativeElement as HTMLElement | null)?.textContent ?? '';
        }

        /**
         * Opens the plugin, then moves it into maintenance with the timers under the test's control: the page starts
         * its checks when maintenance begins.
         */
        async function enterMaintenance(): Promise<void> {
            await open('/plugins/weather');
            // Only the checks of the maintenance count from here, not the load when the plugin opened.
            refresh.mockClear();
            vi.useFakeTimers();
            plugins.set([buildAvailablePlugin({ availability: 'maintenance' })]);
            harness.detectChanges();
        }

        it('shows the maintenance panel instead of the frame', async () => {
            plugins.set([buildAvailablePlugin({ availability: 'maintenance' })]);
            await harness.navigateByUrl('/plugins/weather');
            harness.detectChanges();

            expect(frame()).toBeNull();
            expect(text()).toContain('Weather is being updated. It will be back in a few minutes.');
        });

        it('asks again every 15 seconds and opens the frame once the plugin is ready', async () => {
            await enterMaintenance();
            expect(frame()).toBeNull();

            vi.advanceTimersByTime(PLUGIN_MAINTENANCE_POLL_MS - 1);
            expect(refresh).not.toHaveBeenCalled();
            vi.advanceTimersByTime(1);
            expect(refresh).toHaveBeenCalledTimes(1);
            vi.advanceTimersByTime(PLUGIN_MAINTENANCE_POLL_MS);
            expect(refresh).toHaveBeenCalledTimes(2);

            plugins.set([buildAvailablePlugin()]);
            harness.detectChanges();
            expect(frame()?.getAttribute('src')).toBe(`${FRAME_ORIGIN}/?es_org=3`);
            vi.advanceTimersByTime(PLUGIN_MAINTENANCE_POLL_MS * 2);
            expect(refresh).toHaveBeenCalledTimes(2);
        });

        it('does not ask while the browser tab is hidden', async () => {
            await enterMaintenance();
            const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);

            vi.advanceTimersByTime(PLUGIN_MAINTENANCE_POLL_MS * 2);
            expect(refresh).not.toHaveBeenCalled();

            hidden.mockReturnValue(false);
            vi.advanceTimersByTime(PLUGIN_MAINTENANCE_POLL_MS);
            expect(refresh).toHaveBeenCalledTimes(1);
        });
    });

    describe('when the plugin is not ready', () => {
        const UNAVAILABLE_MESSAGE =
            "EpicStaff couldn't confirm that this plugin's address leads here. Ask your administrator to check it.";

        function text(): string {
            return (harness.routeNativeElement as HTMLElement | null)?.textContent ?? '';
        }

        /** The polite status line under the message. */
        function status(): string | null {
            const line = (harness.routeNativeElement as HTMLElement | null)?.querySelector('[role="status"]');
            return line ? (line.textContent?.trim() ?? '') : null;
        }

        it.each([
            {
                availability: 'unavailable',
                frameOrigin: null,
                message: UNAVAILABLE_MESSAGE,
            },
            {
                // A stale or careless response: the state alone keeps a safe origin from being framed.
                availability: 'unavailable',
                frameOrigin: FRAME_ORIGIN,
                message: UNAVAILABLE_MESSAGE,
            },
            {
                // A state a newer backend may send: never framed by a build that doesn't know it.
                availability: 'suspended',
                frameOrigin: FRAME_ORIGIN,
                message: "EpicStaff doesn't know this plugin's state, so its page was not loaded.",
            },
        ])(
            'frames nothing for $availability with origin $frameOrigin and says why',
            async ({ availability, frameOrigin, message }) => {
                plugins.set([
                    buildAvailablePlugin({
                        availability: availability as AvailablePluginAvailability,
                        frame_origin: frameOrigin,
                    }),
                ]);
                await harness.navigateByUrl('/plugins/weather');
                harness.detectChanges();

                expect(frame()).toBeNull();
                expect(text()).toContain("Weather isn't available right now");
                expect(text()).toContain(message);
            }
        );

        it('removes the frame once the server says the plugin is unavailable', async () => {
            await open('/plugins/weather');

            plugins.set([buildAvailablePlugin({ availability: 'unavailable', frame_origin: null })]);
            harness.detectChanges();

            expect(frame()).toBeNull();
            expect(text()).toContain("Weather isn't available right now");
            expect(text()).toContain('Once the address is corrected, it can take up to a minute to be picked up.');
        });

        it('shows Try again busy while the server is asked, then frames the plugin it says is ready', async () => {
            plugins.set([buildAvailablePlugin({ availability: 'unavailable', frame_origin: null })]);
            await harness.navigateByUrl('/plugins/weather');
            harness.detectChanges();
            refresh.mockClear();
            const response = holdNextRefresh();

            tryAgainButton().click();
            harness.detectChanges();
            expect(tryAgainButton().getAttribute('aria-disabled')).toBe('true');
            tryAgainButton().click();
            expect(refresh).toHaveBeenCalledTimes(1);

            response.next([buildAvailablePlugin()]);
            response.complete();
            harness.detectChanges();

            expect(frame()?.getAttribute('src')).toBe(`${FRAME_ORIGIN}/?es_org=3`);
        });

        it('makes Try again usable again and says so when the server still says unavailable', async () => {
            const unavailable = (): AvailablePlugin =>
                buildAvailablePlugin({ availability: 'unavailable', frame_origin: null });
            plugins.set([unavailable()]);
            await harness.navigateByUrl('/plugins/weather');
            harness.detectChanges();
            expect(status()).toBe('');

            for (const attempt of [1, 2]) {
                const response = holdNextRefresh();
                tryAgainButton().click();
                harness.detectChanges();
                // Emptied while asking, so the same answer is announced again.
                expect(status()).toBe('');
                response.next([unavailable()]);
                response.complete();
                harness.detectChanges();

                expect(frame(), `attempt ${attempt}`).toBeNull();
                expect(tryAgainButton().getAttribute('aria-disabled')).toBeNull();
                expect(status()).toBe('Still unavailable');
            }
        });

        it('does not poll the server, unlike maintenance', async () => {
            await open('/plugins/weather');
            refresh.mockClear();
            // Before the state changes, so a poll it started would run on these timers.
            vi.useFakeTimers();
            plugins.set([buildAvailablePlugin({ availability: 'unavailable', frame_origin: null })]);
            harness.detectChanges();

            vi.advanceTimersByTime(PLUGIN_MAINTENANCE_POLL_MS * 3);

            expect(refresh).not.toHaveBeenCalled();
        });
    });

    describe('availability.changed from the framed page', () => {
        it('asks the server again at once, then at most once per 10 seconds, the last report answered late', async () => {
            const port = handshake(await open('/plugins/weather'));
            refresh.mockClear();
            vi.useFakeTimers();

            port.postMessage({ type: 'availability.changed', state: 'maintenance' });
            expect(refresh).toHaveBeenCalledTimes(1);

            vi.advanceTimersByTime(1000);
            port.postMessage({ type: 'availability.changed', state: 'unavailable' });
            port.postMessage({ type: 'availability.changed', state: 'maintenance' });
            expect(refresh).toHaveBeenCalledTimes(1);

            vi.advanceTimersByTime(PLUGIN_AVAILABILITY_CHECK_MS);
            expect(refresh).toHaveBeenCalledTimes(2);
        });

        it('never acts on the message itself: the server’s answer decides what is shown', async () => {
            const iframe = await open('/plugins/weather');
            const port = handshake(iframe);

            port.postMessage({ type: 'availability.changed', state: 'maintenance' });
            harness.detectChanges();
            expect(frame()).toBe(iframe);

            plugins.set([buildAvailablePlugin({ availability: 'maintenance' })]);
            harness.detectChanges();
            expect(frame()).toBeNull();
            expect(harness.routeNativeElement?.textContent).toContain('Weather is being updated.');

            plugins.set([]);
            harness.detectChanges();
            expect(harness.routeNativeElement?.textContent).toContain('Plugin not available');
        });

        it('ignores available, which says nothing new', async () => {
            const port = handshake(await open('/plugins/weather'));
            refresh.mockClear();

            port.postMessage({ type: 'availability.changed', state: 'available' });

            expect(refresh).not.toHaveBeenCalled();
        });
    });

    it('frames nothing for a plugin that is not available, or whose origin is not safe', async () => {
        await harness.navigateByUrl('/plugins/chat');
        harness.detectChanges();
        expect(frame()).toBeNull();
        expect(harness.routeNativeElement?.textContent).toContain('Plugin not available');
        // Only the load when the page opened: nothing polls for a plugin that is not available.
        expect(refresh).toHaveBeenCalledTimes(1);

        plugins.set([buildAvailablePlugin({ frame_origin: 'http://weather.plugins.example.com' })]);
        await harness.navigateByUrl('/plugins/weather');
        harness.detectChanges();
        expect(frame()).toBeNull();
        expect(harness.routeNativeElement?.textContent).toContain("Couldn't open the plugin");
    });

    it('frames nothing for a ready plugin without an origin', async () => {
        plugins.set([buildAvailablePlugin({ frame_origin: null })]);
        await harness.navigateByUrl('/plugins/weather');
        harness.detectChanges();

        expect(frame()).toBeNull();
        expect(harness.routeNativeElement?.textContent).toContain("Couldn't open the plugin");
        expect(harness.routeNativeElement?.textContent).toContain(
            'EpicStaff got an unexpected address for this plugin, so its page was not loaded.'
        );
    });
});
