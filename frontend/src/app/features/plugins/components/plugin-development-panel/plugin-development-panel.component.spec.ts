import { HttpErrorResponse, HttpHeaders, HttpResponse } from '@angular/common/http';
import { isSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogData, ConfirmationDialogService } from '@shared/components';
import { Observable, of, Subject, throwError } from 'rxjs';
import { type Mock, onTestFinished } from 'vitest';

import { ToastService } from '../../../../services/notifications';
import { PluginDevelopment, PluginDevelopmentUpdate } from '../../models/plugin-development.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildPluginDevelopment, buildPluginDevelopmentTarget } from '../../testing/plugin-fixtures';
import {
    PLUGIN_DEVELOPMENT_HOST_UNRESOLVED,
    PluginDevelopmentPanelComponent,
} from './plugin-development-panel.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const RUNTIME_FILE_NAME = 'weather-development-runtime.json';

/** What the server says of a port equal to the development API port's (serializers/development.py). */
const API_PORT_REFUSAL = 'is the development API port (PLUGINS_DEV_API_PORT); use another port';

/** What the server says when neither port is set. */
const NO_PORT_REFUSAL =
    'needs a backend port or a frontend dev server port; to route nothing, stop development instead';

/** A save refused with the problems listed, as the server's InvalidDevelopmentPortsError answers it. */
function refusedPorts(errors: { loc: string; message: string }[]): HttpErrorResponse {
    const summary = errors.length === 1 ? errors[0].message : `${errors.length} problems found.`;
    return new HttpErrorResponse({
        status: 400,
        error: {
            status_code: 400,
            code: 'invalid',
            message: `The development ports are invalid. ${summary}`,
            errors,
        },
    });
}

/** Replaces the browser's object URLs for one test: jsdom has none. */
function stubObjectUrls(create: (blob: Blob) => string): {
    createObjectUrl: Mock<(blob: Blob) => string>;
    revokeObjectUrl: Mock<(url: string) => void>;
} {
    const createObjectUrl = vi.fn(create);
    const revokeObjectUrl = vi.fn<(url: string) => void>();
    const originals = {
        createObjectURL: Object.getOwnPropertyDescriptor(URL, 'createObjectURL'),
        revokeObjectURL: Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL'),
    };
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, writable: true, value: createObjectUrl });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, writable: true, value: revokeObjectUrl });
    onTestFinished(() => {
        for (const [name, descriptor] of Object.entries(originals)) {
            if (descriptor) Object.defineProperty(URL, name, descriptor);
            else Reflect.deleteProperty(URL, name);
        }
    });
    return { createObjectUrl, revokeObjectUrl };
}

function runtimeFileResponse(body: Blob, contentDisposition: string | null): HttpResponse<Blob> {
    const headers = contentDisposition ? new HttpHeaders({ 'Content-Disposition': contentDisposition }) : undefined;
    return new HttpResponse({ body, headers, status: 200 });
}

describe('PluginDevelopmentPanelComponent', () => {
    let fixture: ComponentFixture<PluginDevelopmentPanelComponent>;
    let element: HTMLElement;
    let storage: {
        getDevelopment: Mock<(identifier: string) => Observable<PluginDevelopment>>;
        updateDevelopment: Mock<(identifier: string, update: PluginDevelopmentUpdate) => Observable<PluginDevelopment>>;
        clearDevelopment: Mock<(identifier: string) => Observable<void>>;
        downloadDevelopmentRuntimeFile: Mock<(identifier: string) => Observable<HttpResponse<Blob>>>;
    };
    let confirm: Mock<(data: ConfirmationDialogData) => Observable<boolean | 'close'>>;
    let toast: { success: Mock; error: Mock };
    let changes: number;

    async function render(development: PluginDevelopment = buildPluginDevelopment()): Promise<void> {
        storage.getDevelopment.mockReturnValue(of(development));
        fixture = TestBed.createComponent(PluginDevelopmentPanelComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.componentRef.setInput('identifier', 'weather');
        fixture.componentRef.setInput('pluginName', 'Weather');
        fixture.componentInstance.changed.subscribe(() => changes++);
        await settle();
    }

    async function settle(): Promise<void> {
        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();
    }

    function text(node: Element | null | undefined): string {
        return node?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    }

    function fact(name: string): string {
        return text(element.querySelector(`[data-fact="${name}"]`));
    }

    function portLabels(): string[] {
        return Array.from(element.querySelectorAll('[data-port] app-input-number')).map(
            (field) => field.querySelector('input')?.getAttribute('aria-label') ?? ''
        );
    }

    function portInput(key: string): HTMLInputElement {
        return element.querySelector<HTMLInputElement>(`[data-port="${key}"] input`)!;
    }

    function portMessage(key: string): string {
        return text(element.querySelector(`[data-port="${key}"] app-input-number small`));
    }

    async function typePort(key: string, value: string): Promise<void> {
        const input = portInput(key);
        input.value = value;
        input.dispatchEvent(new Event('input'));
        await settle();
    }

    function button(label: string): HTMLButtonElement | undefined {
        return Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find(
            (candidate) => candidate.textContent?.trim() === label
        );
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        changes = 0;
        storage = {
            getDevelopment: vi.fn(() => of(buildPluginDevelopment())),
            updateDevelopment: vi.fn(() => of(buildPluginDevelopment())),
            clearDevelopment: vi.fn(() => of(undefined)),
            downloadDevelopmentRuntimeFile: vi.fn(() =>
                of(runtimeFileResponse(new Blob(['{}']), `attachment; filename="${RUNTIME_FILE_NAME}"`))
            ),
        };
        confirm = vi.fn(() => of<boolean | 'close'>(true));
        toast = { success: vi.fn(), error: vi.fn() };
        TestBed.configureTestingModule({
            imports: [PluginDevelopmentPanelComponent],
            providers: [
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                { provide: ToastService, useValue: toast },
            ],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('says development mode is on, where the host resolves, and where a development backend calls EpicStaff', async () => {
        await render();

        expect(storage.getDevelopment).toHaveBeenCalledWith('weather');
        expect(text(element.querySelector('.development__mode'))).toBe('Development mode is on');
        expect(fact('host')).toBe('host.docker.internal resolves to 192.168.65.254');
        expect(fact('api')).toContain('http://127.0.0.1:8082/api/');
        expect(fact('runtime-file')).toBe('Not downloaded');
    });

    it('says how to make host.docker.internal resolve when it does not', async () => {
        await render(buildPluginDevelopment({ host_address: null }));

        expect(fact('host')).toBe(PLUGIN_DEVELOPMENT_HOST_UNRESOLVED);
        expect(PLUGIN_DEVELOPMENT_HOST_UNRESOLVED).toBe(
            'host.docker.internal does not resolve in django_app: start EpicStaff with docker-compose.plugins-dev.yaml'
        );
    });

    it('offers only the ports the current package can use', async () => {
        await render();
        expect(portLabels()).toEqual(['Backend port, 1024 to 65535', 'Frontend dev server port, 1024 to 65535']);

        fixture.destroy();
        await render(buildPluginDevelopment({ can_use_spa: false }));
        expect(portLabels()).toEqual(['Backend port, 1024 to 65535']);

        fixture.destroy();
        await render(buildPluginDevelopment({ can_use_backend: false }));
        expect(portLabels()).toEqual(['Frontend dev server port, 1024 to 65535']);
        expect(button('Download development runtime file')).toBeUndefined();
        expect(fact('runtime-file')).toBe('');

        fixture.destroy();
        await render(buildPluginDevelopment({ can_use_backend: false, can_use_spa: false }));
        expect(portLabels()).toEqual([]);
        expect(text(element)).toContain('Nothing to route yet');
        expect(button('Save')).toBeUndefined();
    });

    it('keeps a port within 1024 to 65535, then saves both ports', async () => {
        await render();
        expect(button('Save')!.disabled).toBe(true);

        await typePort('backend_port', '80');
        expect(portMessage('backend_port')).toBe('Enter a whole number from 1024 to 65535.');
        expect(button('Save')!.disabled).toBe(true);

        await typePort('backend_port', '65536');
        expect(button('Save')!.disabled).toBe(true);

        await typePort('backend_port', '8001');
        expect(portMessage('backend_port')).toBe('');
        button('Save')!.click();
        await settle();

        expect(storage.updateDevelopment).toHaveBeenCalledWith('weather', { backend_port: 8001, spa_port: null });
        expect(changes).toBe(1);
        expect(toast.success).toHaveBeenCalled();
    });

    it('sends null for a port the package cannot use, and keeps a stored one it can', async () => {
        await render(
            buildPluginDevelopment({
                can_use_spa: false,
                target: buildPluginDevelopmentTarget({ backend_port: 8001, spa_port: 5173 }),
            })
        );

        await typePort('backend_port', '8002');
        button('Save')!.click();

        expect(storage.updateDevelopment).toHaveBeenCalledWith('weather', { backend_port: 8002, spa_port: null });
    });

    it('will not save with every port empty, and says to stop development instead', async () => {
        await render(buildPluginDevelopment({ target: buildPluginDevelopmentTarget({ spa_port: null }) }));

        await typePort('backend_port', '');

        expect(button('Save')!.disabled).toBe(true);
        expect(text(element)).toContain('Set at least one port, or stop development.');
    });

    it("shows a refused save's error on the port it names, until that port is typed in again", async () => {
        storage.updateDevelopment.mockReturnValue(
            throwError(() => refusedPorts([{ loc: 'backend_port', message: API_PORT_REFUSAL }]))
        );
        await render();

        await typePort('backend_port', '8082');
        button('Save')!.click();
        await settle();

        expect(portMessage('backend_port')).toBe(API_PORT_REFUSAL);
        expect(portInput('backend_port').getAttribute('aria-invalid')).toBe('true');
        expect(text(element.querySelector('.development__error > span'))).toBe('The request was not valid.');
        expect(element.querySelector('.development__error-items')).toBeNull();
        expect(changes).toBe(0);

        await typePort('backend_port', '8083');

        expect(portMessage('backend_port')).toBe('');
        expect(portInput('backend_port').getAttribute('aria-invalid')).toBe('false');
        expect(button('Save')!.disabled).toBe(false);
    });

    it("lists a refused save's problems that name no port above the ports", async () => {
        storage.updateDevelopment.mockReturnValue(
            throwError(() => refusedPorts([{ loc: 'non_field_errors', message: NO_PORT_REFUSAL }]))
        );
        await render();

        await typePort('spa_port', '5173');
        button('Save')!.click();
        await settle();

        expect(Array.from(element.querySelectorAll('.development__error-items li')).map((item) => text(item))).toEqual([
            NO_PORT_REFUSAL,
        ]);
        expect(portMessage('backend_port')).toBe('');
        expect(portMessage('spa_port')).toBe('');
    });

    it('says when the deployment turned development mode off meanwhile', async () => {
        storage.updateDevelopment.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 409,
                        error: {
                            status_code: 409,
                            code: 'plugin_development_mode_off',
                            message: 'Plugin development mode is off on this deployment.',
                        },
                    })
            )
        );
        await render();

        await typePort('spa_port', '5173');
        button('Save')!.click();
        await settle();

        expect(text(element.querySelector('.development__error'))).toBe(
            'Plugin development mode is off on this deployment.'
        );
    });

    it('stops development only after confirmation, then shows the state again', async () => {
        await render(buildPluginDevelopment({ target: buildPluginDevelopmentTarget() }));
        confirm.mockReturnValueOnce(of(false));

        button('Stop development')!.click();
        expect(storage.clearDevelopment).not.toHaveBeenCalled();

        button('Stop development')!.click();
        await settle();

        expect(confirm).toHaveBeenLastCalledWith(
            expect.objectContaining({
                title: 'Stop development?',
                message: 'Weather is served from its installed package again, and the development keys stop working.',
            })
        );
        expect(storage.clearDevelopment).toHaveBeenCalledWith('weather');
        expect(storage.getDevelopment).toHaveBeenCalledTimes(2);
        expect(changes).toBe(1);
    });

    it('keeps ports typed but not saved through a download and a failed stop, and starts over after a stop', async () => {
        stubObjectUrls(() => 'blob:x');
        const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
        onTestFinished(() => click.mockRestore());
        await render(buildPluginDevelopment({ target: buildPluginDevelopmentTarget() }));
        await typePort('backend_port', '9001');

        button('Download development runtime file')!.click();
        await settle();
        expect(storage.getDevelopment).toHaveBeenCalledTimes(2);
        expect(portInput('backend_port').value).toBe('9001');

        storage.clearDevelopment.mockReturnValueOnce(
            throwError(() => new HttpErrorResponse({ status: 502, statusText: 'Bad Gateway', error: '<html></html>' }))
        );
        button('Stop development')!.click();
        await settle();
        expect(toast.error).toHaveBeenCalledWith("Couldn't stop development.");
        expect(storage.getDevelopment).toHaveBeenCalledTimes(3);
        expect(portInput('backend_port').value).toBe('9001');
        expect(button('Save')!.disabled).toBe(false);

        storage.getDevelopment.mockReturnValue(of(buildPluginDevelopment()));
        button('Stop development')!.click();
        await settle();
        expect(portInput('backend_port').value).toBe('');
        expect(button('Save')!.disabled).toBe(true);
    });

    it('shows the spinner, not an empty panel, while Retry loads the state again', async () => {
        const loaded = new Subject<PluginDevelopment>();
        storage.getDevelopment.mockReturnValueOnce(
            throwError(() => new HttpErrorResponse({ status: 502, statusText: 'Bad Gateway', error: '<html></html>' }))
        );
        await render();
        expect(text(element.querySelector('app-fetch-error-state h3'))).toBe("Couldn't load the development state");

        storage.getDevelopment.mockReturnValueOnce(loaded);
        button('Retry')!.click();
        await settle();
        expect(element.querySelector('app-fetch-error-state')).toBeNull();
        expect(element.querySelector('app-loading-spinner')).not.toBeNull();

        loaded.next(buildPluginDevelopment());
        loaded.complete();
        await settle();
        expect(element.querySelector('app-loading-spinner')).toBeNull();
        expect(text(element.querySelector('.development__mode'))).toBe('Development mode is on');
    });

    it('offers Stop development while development keys are in use, even with no target', async () => {
        await render(buildPluginDevelopment({ runtime_file_issued_at: '2026-10-22T09:00:00Z' }));
        expect(button('Stop development')).toBeDefined();

        fixture.destroy();
        await render();
        expect(button('Stop development')).toBeUndefined();
    });

    it('downloads the runtime file after confirmation, under the server’s name, without reading or keeping it', async () => {
        const file = new Blob(['{"service_accounts": []}'], { type: 'application/json' });
        storage.downloadDevelopmentRuntimeFile.mockReturnValue(
            of(runtimeFileResponse(file, `attachment; filename="${RUNTIME_FILE_NAME}"`))
        );
        // Every way a page could read a Blob that this browser has.
        const readers = [
            ...(['text', 'arrayBuffer', 'stream'] as const)
                .filter((method) => typeof Blob.prototype[method] === 'function')
                .map((method) => vi.spyOn(Blob.prototype, method)),
            vi.spyOn(FileReader.prototype, 'readAsText'),
            vi.spyOn(FileReader.prototype, 'readAsArrayBuffer'),
            vi.spyOn(JSON, 'parse'),
        ];
        const loggers = (['log', 'info', 'debug', 'warn', 'error'] as const).map((method) => vi.spyOn(console, method));
        const { createObjectUrl, revokeObjectUrl } = stubObjectUrls((blob) =>
            blob === file ? 'blob:runtime-file' : 'blob:other'
        );
        const saved: { href: string; download: string }[] = [];
        const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
            this: HTMLAnchorElement
        ) {
            saved.push({ href: this.href, download: this.download });
        });
        await render(buildPluginDevelopment({ target: buildPluginDevelopmentTarget() }));

        button('Download development runtime file')!.click();
        await settle();

        expect(confirm).toHaveBeenCalledWith(
            expect.objectContaining({
                title: 'Download the development runtime file?',
                message:
                    'This file holds keys that act for Weather in every organization it is granted to, and the ' +
                    'plugin&#39;s secret settings. Keep it outside your plugin&#39;s source. Downloading again stops ' +
                    'the previous file&#39;s keys.',
            })
        );
        expect(storage.downloadDevelopmentRuntimeFile).toHaveBeenCalledWith('weather');
        expect(createObjectUrl).toHaveBeenCalledWith(file);
        expect(saved).toEqual([{ href: 'blob:runtime-file', download: RUNTIME_FILE_NAME }]);
        expect(revokeObjectUrl).toHaveBeenCalledWith('blob:runtime-file');
        for (const reader of readers) expect(reader).not.toHaveBeenCalled();
        for (const logger of loggers) expect(logger).not.toHaveBeenCalled();
        const held = Object.values(fixture.componentInstance as object)
            .filter(isSignal)
            .map((state) => (state as () => unknown)());
        expect(held.some((value) => value instanceof Blob || value instanceof HttpResponse)).toBe(false);
        // The issue time comes from the server again.
        expect(storage.getDevelopment).toHaveBeenCalledTimes(2);

        click.mockRestore();
        for (const spy of [...readers, ...loggers]) spy.mockRestore();
    });

    it('saves under the documented name when the server names no file', async () => {
        stubObjectUrls(() => 'blob:x');
        const names: string[] = [];
        const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
            this: HTMLAnchorElement
        ) {
            names.push(this.download);
        });
        storage.downloadDevelopmentRuntimeFile.mockReturnValue(of(runtimeFileResponse(new Blob(['{}']), null)));
        await render();

        button('Download development runtime file')!.click();
        await settle();

        expect(names).toEqual([RUNTIME_FILE_NAME]);
        click.mockRestore();
    });

    it('downloads nothing when the confirmation is declined, and says why a download was refused', async () => {
        await render();
        confirm.mockReturnValueOnce(of('close'));

        button('Download development runtime file')!.click();
        expect(storage.downloadDevelopmentRuntimeFile).not.toHaveBeenCalled();

        storage.downloadDevelopmentRuntimeFile.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 409,
                        error: { status_code: 409, code: 'plugin_not_running', message: 'The plugin is not running.' },
                    })
            )
        );
        button('Download development runtime file')!.click();
        await settle();

        expect(toast.error).toHaveBeenCalledWith('The plugin is not running yet. Try again once it runs.');
    });

    it('shows when the file was downloaded, and asks for one while a backend port has no keys', async () => {
        await render(buildPluginDevelopment({ target: buildPluginDevelopmentTarget() }));
        expect(text(element.querySelector('.development__callout'))).toContain('Download the development runtime file');

        fixture.destroy();
        await render(
            buildPluginDevelopment({
                target: buildPluginDevelopmentTarget(),
                runtime_file_issued_at: '2026-10-22T09:30:00Z',
            })
        );
        expect(fact('runtime-file')).toMatch(/^Downloaded /);
        expect(element.querySelector('.development__callout')).toBeNull();
    });

    it('gives the command that runs the backend with the file, on the stored backend port or 8001', async () => {
        await render();
        expect(text(element.querySelector('app-copy-field .value'))).toBe(
            'epicstaff-plugin dev <your plugin directory> --runtime-file <downloaded file> --port 8001'
        );

        fixture.destroy();
        await render(buildPluginDevelopment({ target: buildPluginDevelopmentTarget({ backend_port: 9001 }) }));
        expect(text(element.querySelector('app-copy-field .value'))).toBe(
            'epicstaff-plugin dev <your plugin directory> --runtime-file <downloaded file> --port 9001'
        );
    });

    it('offers only Stop development when the deployment turned the mode off since the page loaded', async () => {
        await render(
            buildPluginDevelopment({
                development_mode: false,
                host_address: null,
                api_url: null,
                target: buildPluginDevelopmentTarget(),
            })
        );

        expect(text(element)).toContain('Plugin development mode is off on this deployment.');
        expect(portLabels()).toEqual([]);
        expect(button('Save')).toBeUndefined();
        expect(button('Download development runtime file')).toBeUndefined();
        expect(button('Stop development')).toBeDefined();
    });
});
