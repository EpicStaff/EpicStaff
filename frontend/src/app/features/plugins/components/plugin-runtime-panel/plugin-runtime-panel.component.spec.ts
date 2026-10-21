import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { Observable, of } from 'rxjs';
import type { Mock } from 'vitest';

import { ToastService } from '../../../../services/notifications';
import { PluginRuntimeResponse } from '../../models/plugin-backend.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildPluginPlacement, buildPluginRuntime } from '../../testing/plugin-fixtures';
import { PLUGIN_RUNTIME_POLL_MS, PluginRuntimePanelComponent } from './plugin-runtime-panel.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('PluginRuntimePanelComponent', () => {
    let fixture: ComponentFixture<PluginRuntimePanelComponent>;
    let element: HTMLElement;
    let storage: {
        getRuntime: Mock<(identifier: string) => Observable<PluginRuntimeResponse>>;
        restart: Mock<(identifier: string) => Observable<PluginRuntimeResponse>>;
    };
    let confirm: Mock<() => Observable<boolean | 'close'>>;
    let changes: number;

    function render(): void {
        fixture = TestBed.createComponent(PluginRuntimePanelComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.componentRef.setInput('identifier', 'weather');
        fixture.componentRef.setInput('pluginName', 'Weather');
        fixture.componentInstance.runtimeChanged.subscribe(() => changes++);
        fixture.detectChanges();
        TestBed.tick();
        vi.advanceTimersByTime(0);
        fixture.detectChanges();
    }

    function poll(): void {
        vi.advanceTimersByTime(PLUGIN_RUNTIME_POLL_MS);
        fixture.detectChanges();
    }

    function fact(term: string): string | undefined {
        const terms = Array.from(element.querySelectorAll('dt'));
        return terms
            .find((dt) => dt.textContent?.trim() === term)
            ?.nextElementSibling?.textContent?.replace(/\s+/g, ' ')
            .trim();
    }

    function restartButton(): HTMLButtonElement {
        return Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find(
            (button) => button.textContent?.trim() === 'Restart'
        )!;
    }

    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        changes = 0;
        storage = {
            getRuntime: vi.fn(() => of(buildPluginRuntime())),
            restart: vi.fn(() =>
                of(buildPluginRuntime({ placement: buildPluginPlacement({ observed_state: 'starting' }) }))
            ),
        };
        confirm = vi.fn(() => of<boolean | 'close'>(true));
        TestBed.configureTestingModule({
            imports: [PluginRuntimePanelComponent],
            providers: [
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
            ],
        });
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it('shows the node and the placement of a running plugin', () => {
        render();

        expect(fact('Name')).toContain('node-1');
        expect(fact('Name')).toContain('Online');
        expect(fact('Agent version')).toBe('0.1.0');
        expect(fact('Port')).toBe('20001');
        expect(fact('UID')).toBe('20001');
        expect(fact('Desired state')).toBe('Running');
        expect(fact('Observed state')).toBe('Running');
        expect(fact('Health')).toBe('Healthy');
        expect(fact('Version')).toBe('0.2.0');
        expect(fact('PID')).toBe('412');
        expect(fact('Restarts')).toBe('0');
        expect(fact('Memory')).toBe('61.4 MB');
        expect(element.querySelector('.runtime__log')).toBeNull();
    });

    it('shows the last error and the log tail of a failed plugin, and why a plugin is held stopped', () => {
        storage.getRuntime.mockReturnValue(
            of(
                buildPluginRuntime({
                    node: { name: 'node-1', online: false, last_seen_at: null, agent_version: null },
                    placement: buildPluginPlacement({
                        desired_state: 'stopped',
                        blocked_reason: 'required_settings_missing',
                        observed_state: 'failed',
                        health: 'failing',
                        pid: null,
                        rss_mb: null,
                        last_error: 'ModuleNotFoundError: No module named weather_plugin',
                        log_tail: ['Traceback (most recent call last):', '  File "app.py", line 1'],
                    }),
                })
            )
        );
        render();

        expect(fact('Name')).toContain('Offline');
        expect(fact('Last seen')).toBe('Never');
        expect(fact('Observed state')).toBe('Failed');
        expect(fact('Memory')).toBe('—');
        expect(element.querySelector('.runtime__blocked')?.textContent).toContain('required settings are not set');
        expect(element.querySelector('.runtime__error')?.textContent).toBe(
            'ModuleNotFoundError: No module named weather_plugin'
        );
        expect(element.querySelector('.runtime__log')?.textContent).toBe(
            'Traceback (most recent call last):\n  File "app.py", line 1'
        );
    });

    it('says when the plugin has no node or no process yet', () => {
        storage.getRuntime.mockReturnValue(of({ node: null, placement: null }));
        render();

        expect(element.textContent).toContain('No plugin node is registered');
        expect(element.textContent).toContain('The plugin has no process yet.');
        expect(restartButton().disabled).toBe(true);
    });

    it('polls while shown and stops when destroyed', () => {
        render();
        expect(storage.getRuntime).toHaveBeenCalledTimes(1);

        poll();
        poll();
        expect(storage.getRuntime).toHaveBeenCalledTimes(3);

        fixture.destroy();
        vi.advanceTimersByTime(PLUGIN_RUNTIME_POLL_MS * 3);
        expect(storage.getRuntime).toHaveBeenCalledTimes(3);
    });

    it('skips the polls while the browser tab is hidden', () => {
        let hidden = true;
        const hiddenProperty = vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
        try {
            render();
            poll();
            expect(storage.getRuntime).not.toHaveBeenCalled();

            hidden = false;
            poll();
            expect(storage.getRuntime).toHaveBeenCalledTimes(1);
        } finally {
            hiddenProperty.mockRestore();
        }
    });

    it('tells when the process moved between polls, so the plugin state can be reloaded', () => {
        render();
        poll();
        expect(changes).toBe(0);

        storage.getRuntime.mockReturnValue(
            of(buildPluginRuntime({ placement: buildPluginPlacement({ observed_state: 'failed' }) }))
        );
        poll();

        expect(changes).toBe(1);
        expect(fact('Observed state')).toBe('Failed');
    });

    it('restarts only after confirmation', () => {
        render();

        confirm.mockReturnValueOnce(of(false));
        restartButton().click();
        expect(storage.restart).not.toHaveBeenCalled();

        restartButton().click();
        fixture.detectChanges();

        expect(confirm).toHaveBeenCalledTimes(2);
        expect(storage.restart).toHaveBeenCalledWith('weather');
        // Once, although the answer also moved the process from running to starting.
        expect(changes).toBe(1);
        expect(fact('Observed state')).toBe('Starting');
    });
});
