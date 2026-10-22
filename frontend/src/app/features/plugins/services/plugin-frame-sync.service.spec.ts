import { signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { PLUGIN_FRAME_LIMITS } from '../constants/plugin-frame-protocol.constants';
import { PluginTheme } from '../models/plugin-frame-protocol.model';
import {
    createPluginFrame,
    FakeMessageChannel,
    FakeMessagePort,
    PluginFrame,
    postFromWindow,
} from '../testing/plugin-frame-test-harness';
import { PluginFrameAttachOptions, PluginFrameSyncService } from './plugin-frame-sync.service';
import { PluginHostThemeService } from './plugin-host-theme.service';

const FRAME_ORIGIN = 'https://weather.plugins.example.com';
const DARK_THEME: PluginTheme = { mode: 'dark', tokens: { '--es-color-accent': '#685fff' } };

describe('PluginFrameSyncService', () => {
    let service: PluginFrameSyncService;
    let theme: WritableSignal<PluginTheme>;
    let pluginFrame: PluginFrame;
    let navChanges: { path: string; replace: boolean }[];
    let availabilityChanges: string[];

    beforeEach(() => {
        vi.stubGlobal('MessageChannel', FakeMessageChannel);
        theme = signal(DARK_THEME);
        navChanges = [];
        availabilityChanges = [];
        TestBed.configureTestingModule({
            providers: [PluginFrameSyncService, { provide: PluginHostThemeService, useValue: { theme } }],
        });
        service = TestBed.inject(PluginFrameSyncService);
        pluginFrame = createPluginFrame();
    });

    afterEach(() => {
        service.detach();
        vi.unstubAllGlobals();
        vi.useRealTimers();
        document.body.innerHTML = '';
    });

    function attach(overrides: Partial<PluginFrameAttachOptions> = {}): void {
        service.attach(pluginFrame.frame, {
            frameOrigin: FRAME_ORIGIN,
            initialPath: '/forecast?city=Berlin',
            org: { id: 3, name: 'Acme' },
            onNavChanged: (path, replace) => navChanges.push({ path, replace }),
            onAvailabilityChanged: (state) => availabilityChanges.push(state),
            ...overrides,
        });
    }

    /** Posts `es:ready` from the frame and returns the port EpicStaff transferred with its answer. */
    function handshake(): FakeMessagePort {
        postFromWindow(pluginFrame.frameWindow, { type: 'es:ready', protocol: 1 }, FRAME_ORIGIN);
        const port = pluginFrame.posted.at(-1)?.transfer[0];
        if (!(port instanceof FakeMessagePort)) throw new Error('no port was transferred');
        return port;
    }

    describe('handshake', () => {
        it('answers es:ready from the frame with es:init, posted to the exact plugin origin with a port', () => {
            attach();

            handshake();

            expect(pluginFrame.posted).toHaveLength(1);
            expect(pluginFrame.posted[0]).toEqual({
                message: {
                    type: 'es:init',
                    protocol: 1,
                    theme: DARK_THEME,
                    nav: { path: '/forecast?city=Berlin' },
                    org: { id: 3, name: 'Acme' },
                },
                targetOrigin: FRAME_ORIGIN,
                transfer: [expect.any(FakeMessagePort)],
            });
        });

        it.each([
            ['another origin', 'https://evil.example'],
            ["EpicStaff's own origin", window.location.origin],
            ['the opaque origin of a sandboxed page', 'null'],
            ['a sibling plugin', 'https://chat.plugins.example.com'],
        ])('ignores es:ready from %s', (_label, origin) => {
            attach();

            postFromWindow(pluginFrame.frameWindow, { type: 'es:ready', protocol: 1 }, origin);

            expect(pluginFrame.posted).toEqual([]);
        });

        it('ignores es:ready whose source is not the frame, even from the plugin origin', () => {
            attach();
            const otherFrame = createPluginFrame();

            postFromWindow(window, { type: 'es:ready', protocol: 1 }, FRAME_ORIGIN);
            postFromWindow(otherFrame.frameWindow, { type: 'es:ready', protocol: 1 }, FRAME_ORIGIN);
            postFromWindow(null, { type: 'es:ready', protocol: 1 }, FRAME_ORIGIN);

            expect(pluginFrame.posted).toEqual([]);
            expect(otherFrame.posted).toEqual([]);
        });

        it('ignores other messages on the window, and everything once detached', () => {
            attach();
            postFromWindow(pluginFrame.frameWindow, { type: 'nav.changed', path: '/x' }, FRAME_ORIGIN);
            postFromWindow(pluginFrame.frameWindow, 'es:ready', FRAME_ORIGIN);
            service.detach();
            postFromWindow(pluginFrame.frameWindow, { type: 'es:ready', protocol: 1 }, FRAME_ORIGIN);

            expect(pluginFrame.posted).toEqual([]);
        });

        it('answers es:error without a port when the page speaks another protocol', () => {
            attach();

            postFromWindow(pluginFrame.frameWindow, { type: 'es:ready', protocol: 2 }, FRAME_ORIGIN);

            expect(pluginFrame.posted).toEqual([
                {
                    message: { type: 'es:error', protocol: 1, code: 'unsupported_protocol' },
                    targetOrigin: FRAME_ORIGIN,
                    transfer: [],
                },
            ]);
        });

        it('a second es:ready (the page reloaded) closes the old port and repeats es:init at the current path', () => {
            attach();
            const firstPort = handshake();
            service.notifyNavigation('/about');

            const secondPort = handshake();

            expect(secondPort).not.toBe(firstPort);
            expect(firstPort.partner?.closed).toBe(true);
            expect(pluginFrame.posted).toHaveLength(2);
            expect(pluginFrame.posted[1].message).toMatchObject({ type: 'es:init', nav: { path: '/about' } });
            firstPort.postMessage({ type: 'nav.changed', path: '/stale', replace: false });
            expect(navChanges).toEqual([]);
        });
    });

    describe('port messages', () => {
        it('passes a canonical nav.changed on, and drops an invalid path or an unknown type', () => {
            attach();
            const port = handshake();

            port.postMessage({ type: 'nav.changed', path: '/forecast?city=Paris', replace: false });
            port.postMessage({ type: 'nav.changed', path: '/a%7e?q=a+b', replace: true });
            port.postMessage({ type: 'nav.changed', path: '/../admin', replace: false });
            port.postMessage({ type: 'nav.changed', path: 'https://evil.example/', replace: false });
            port.postMessage({ type: 'something.new', path: '/x' });

            expect(navChanges).toEqual([
                { path: '/forecast?city=Paris', replace: false },
                { path: '/a~?q=a%20b', replace: true },
            ]);
        });

        it('accepts at most 120 nav.changed a minute, then accepts again once the window moves on', () => {
            vi.useFakeTimers();
            attach();
            const port = handshake();
            const limit = PLUGIN_FRAME_LIMITS.maxNavChangesPerMinute;

            for (let index = 0; index < limit + 5; index++) {
                port.postMessage({ type: 'nav.changed', path: `/page/${index}`, replace: false });
            }
            expect(navChanges).toHaveLength(limit);
            expect(navChanges.at(-1)?.path).toBe(`/page/${limit - 1}`);

            vi.advanceTimersByTime(60_000);
            port.postMessage({ type: 'nav.changed', path: '/later', replace: true });
            expect(navChanges.at(-1)).toEqual({ path: '/later', replace: true });
        });

        it('keeps the rate window across a re-handshake, so reloading cannot reset it', () => {
            vi.useFakeTimers();
            attach();
            let port = handshake();
            for (let index = 0; index < PLUGIN_FRAME_LIMITS.maxNavChangesPerMinute; index++) {
                port.postMessage({ type: 'nav.changed', path: `/page/${index}`, replace: false });
            }

            port = handshake();
            port.postMessage({ type: 'nav.changed', path: '/after-reload', replace: false });

            expect(navChanges.at(-1)?.path).not.toBe('/after-reload');
        });

        it('passes availability.changed on for maintenance and unavailable only', () => {
            attach();
            const port = handshake();

            port.postMessage({ type: 'availability.changed', state: 'maintenance' });
            port.postMessage({ type: 'availability.changed', state: 'available' });
            port.postMessage({ type: 'availability.changed', state: 'down' });
            port.postMessage({ type: 'availability.changed' });
            port.postMessage({ type: 'availability.changed', state: 'unavailable' });

            expect(availabilityChanges).toEqual(['maintenance', 'unavailable']);
            expect(navChanges).toEqual([]);
        });

        it('accepts at most 6 availability.changed a minute, also across a re-handshake', () => {
            vi.useFakeTimers();
            attach();
            let port = handshake();
            const limit = PLUGIN_FRAME_LIMITS.maxAvailabilityChangesPerMinute;
            for (let index = 0; index < limit; index++) {
                port.postMessage({ type: 'availability.changed', state: 'maintenance' });
            }

            port = handshake();
            port.postMessage({ type: 'availability.changed', state: 'unavailable' });
            expect(availabilityChanges).toHaveLength(limit);
            expect(availabilityChanges).not.toContain('unavailable');

            vi.advanceTimersByTime(60_000);
            port.postMessage({ type: 'availability.changed', state: 'unavailable' });
            expect(availabilityChanges.at(-1)).toBe('unavailable');
        });

        it('counts nav.changed and availability.changed in windows of their own', () => {
            attach();
            const port = handshake();
            for (let index = 0; index < PLUGIN_FRAME_LIMITS.maxAvailabilityChangesPerMinute; index++) {
                port.postMessage({ type: 'availability.changed', state: 'maintenance' });
            }

            port.postMessage({ type: 'nav.changed', path: '/places', replace: false });

            expect(navChanges).toEqual([{ path: '/places', replace: false }]);
        });

        it('sends nav.navigate for a new EpicStaff address, and nothing for the path the page shows', () => {
            attach();
            const port = handshake();
            port.postMessage({ type: 'nav.changed', path: '/about', replace: false });

            service.notifyNavigation('/about');
            service.notifyNavigation('/forecast?city=Rome');

            expect(port.received).toEqual([{ type: 'nav.navigate', path: '/forecast?city=Rome' }]);
        });

        it('sends theme.changed when the theme changes, and nothing when it stays the same', () => {
            attach();
            const port = handshake();
            const lightTheme: PluginTheme = { mode: 'light', tokens: { '--es-color-accent': '#5b52f0' } };

            TestBed.tick();
            expect(port.received).toEqual([]);

            theme.set(lightTheme);
            TestBed.tick();

            expect(port.received).toEqual([{ type: 'theme.changed', theme: lightTheme }]);
        });
    });
});
