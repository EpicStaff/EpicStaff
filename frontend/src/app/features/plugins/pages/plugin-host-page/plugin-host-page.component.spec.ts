import { HttpErrorResponse } from '@angular/common/http';
import { signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { DomSanitizer } from '@angular/platform-browser';
import { Observable, of, Subject, throwError } from 'rxjs';

import { PluginBridgeHost, PluginBridgeStopReason } from '../../bridge/plugin-bridge-host.service';
import { buildUiSession } from '../../bridge/testing/bridge-test-harness';
import { PluginUiSession } from '../../models/plugin.model';
import { PluginsApiService } from '../../services/plugins-api.service';
import { PluginsStoreService } from '../../services/plugins-store.service';
import { PluginHostPageComponent } from './plugin-host-page.component';

// jsdom has no ResizeObserver; the overflow directive inside the error state's button only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('PluginHostPageComponent', () => {
    let fixture: ComponentFixture<PluginHostPageComponent>;
    let createUiSession: ReturnType<typeof vi.fn<(id: number) => Observable<PluginUiSession>>>;
    let refreshNav: ReturnType<typeof vi.fn<() => void>>;
    let bridge: {
        attach: ReturnType<typeof vi.fn>;
        detach: ReturnType<typeof vi.fn>;
        onFrameLoad: ReturnType<typeof vi.fn>;
        stopped: WritableSignal<PluginBridgeStopReason | null>;
    };

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        createUiSession = vi.fn<(id: number) => Observable<PluginUiSession>>();
        refreshNav = vi.fn<() => void>();
        bridge = {
            attach: vi.fn(),
            detach: vi.fn(),
            onFrameLoad: vi.fn(),
            stopped: signal<PluginBridgeStopReason | null>(null),
        };
        TestBed.configureTestingModule({
            imports: [PluginHostPageComponent],
            providers: [
                { provide: PluginsApiService, useValue: { createUiSession } },
                { provide: PluginsStoreService, useValue: { refreshNav } },
            ],
        });
        TestBed.overrideComponent(PluginHostPageComponent, {
            set: { providers: [{ provide: PluginBridgeHost, useValue: bridge }] },
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    async function open(id = '7'): Promise<HTMLElement> {
        fixture = TestBed.createComponent(PluginHostPageComponent);
        fixture.componentRef.setInput('id', id);
        await fixture.whenStable();
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    it('renders the page in an iframe with literal sandbox, referrer and permission attributes', async () => {
        createUiSession.mockReturnValue(of(buildUiSession()));

        const element = await open();
        const frame = element.querySelector('iframe');

        expect(createUiSession).toHaveBeenCalledWith(7);
        expect(frame?.getAttribute('sandbox')).toBe('allow-scripts');
        expect(frame?.getAttribute('referrerpolicy')).toBe('no-referrer');
        expect(frame?.getAttribute('allow')).toBe("camera 'none'; microphone 'none'; geolocation 'none'");
        expect(frame?.getAttribute('src')).toBe('/api/plugin-ui/token-1/index.html');
        expect(bridge.attach).toHaveBeenCalledWith(frame, expect.objectContaining({ token: 'token-1' }));
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

    it('does not ask for a session for an id that is not a positive integer', async () => {
        const element = await open('abc');

        expect(createUiSession).not.toHaveBeenCalled();
        expect(element.textContent).toContain('Plugin not found');
    });

    it('drops the iframe and says why when the bridge stops the page', async () => {
        createUiSession.mockReturnValue(of(buildUiSession()));
        await open();

        bridge.stopped.set('navigated');
        await fixture.whenStable();
        fixture.detectChanges();
        const element = fixture.nativeElement as HTMLElement;

        expect(element.querySelector('iframe')).toBeNull();
        expect(element.textContent).toContain('Plugin page stopped');
    });
});
