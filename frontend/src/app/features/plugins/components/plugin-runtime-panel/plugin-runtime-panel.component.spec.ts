import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { Observable, of } from 'rxjs';
import { type Mock, onTestFinished } from 'vitest';

import { ToastService } from '../../../../services/notifications';
import { PluginBackupList, PluginRestore, PluginUpgrade } from '../../models/plugin-admin.model';
import { PluginDatabaseState, PluginRuntimeResponse } from '../../models/plugin-backend.model';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import {
    buildFailedMigrationUpgrade,
    buildPluginBackup,
    buildPluginBackupList,
    buildPluginPlacement,
    buildPluginRestore,
    buildPluginRuntime,
    buildPluginRuntimeDatabase,
} from '../../testing/plugin-fixtures';
import { PluginRestoreDialogData } from '../plugin-restore-dialog/plugin-restore-dialog.component';
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
        listBackups: Mock<(identifier: string) => Observable<PluginBackupList>>;
    };
    let openRestore: Mock<(data: PluginRestoreDialogData) => Observable<PluginRestore | undefined>>;
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

    function section(title: string): HTMLElement | undefined {
        return Array.from(element.querySelectorAll<HTMLElement>('.runtime__section')).find(
            (candidate) => candidate.querySelector('h3')?.textContent?.trim() === title
        );
    }

    function sectionTitles(): string[] {
        return Array.from(element.querySelectorAll('.runtime__section h3')).map(
            (heading) => heading.textContent?.trim() ?? ''
        );
    }

    function text(node: Element | null | undefined): string {
        return node?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
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
            listBackups: vi.fn(() => of(buildPluginBackupList())),
        };
        openRestore = vi.fn(() => of<PluginRestore | undefined>(undefined));
        confirm = vi.fn(() => of<boolean | 'close'>(true));
        TestBed.configureTestingModule({
            imports: [PluginRuntimePanelComponent],
            providers: [
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
                { provide: PluginDialogsService, useValue: { openRestore } },
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
        expect(section('Process')?.querySelector('.runtime__callout')?.textContent).toContain(
            'required settings are not set'
        );
        expect(element.querySelector('.runtime__error')?.textContent).toBe(
            'ModuleNotFoundError: No module named weather_plugin'
        );
        expect(element.querySelector('.runtime__log')?.textContent).toBe(
            'Traceback (most recent call last):\n  File "app.py", line 1'
        );
    });

    it('says when the plugin has no node or no process yet', () => {
        storage.getRuntime.mockReturnValue(
            of({ node: null, placement: null, database: null, egress: null, upgrade: null })
        );
        render();

        expect(element.textContent).toContain('No plugin node is registered');
        expect(element.textContent).toContain('The plugin has no process yet.');
        expect(restartButton().disabled).toBe(true);
    });

    it('shows the database of a plugin that has one, and lists its migrations on request', () => {
        storage.getRuntime.mockReturnValue(of(buildPluginRuntime({ database: buildPluginRuntimeDatabase() })));
        render();

        const database = section('Database')!;
        expect(text(database.querySelector('app-plugin-badge'))).toBe('Ready');
        expect(fact('Server')).toBe('plugins_db (plugins_db:5432)');
        expect(fact('Database')).toBe('plugin_weather');
        expect(fact('Owner role')).toBe('weather_owner');
        expect(fact('App role')).toBe('weather_app');
        expect(fact('Job role')).toBe('weather_job');
        expect(fact('Migrations')).toMatch(/^1 of 1 /);
        const disclosure = database.querySelector('details')!;
        expect(disclosure.open).toBe(false);
        expect(text(disclosure.querySelector('summary'))).toBe('Applied migrations');
        expect(Array.from(disclosure.querySelectorAll('li')).map((item) => text(item))).toEqual(['001_weather.sql']);
        expect(fact('Connection limit')).toBe('3');
        expect(fact('Statement timeout')).toBe('10 s');
        expect(fact('Size')).toBe('7.3 MB');
        expect(database.querySelector('.runtime__callout')).toBeNull();
        expect(database.querySelector('.runtime__error')).toBeNull();
    });

    it.each<[PluginDatabaseState, string]>([
        ['pending', 'Waiting for the node'],
        ['provisioning', 'Setting up'],
        ['ready', 'Ready'],
        ['failed', 'Failed'],
    ])('shows a database that is %s as "%s"', (state, label) => {
        storage.getRuntime.mockReturnValue(of(buildPluginRuntime({ database: buildPluginRuntimeDatabase({ state }) })));
        render();

        expect(text(section('Database')!.querySelector('app-plugin-badge'))).toBe(label);
    });

    it('shows a database not set up yet with no migration list and no size', () => {
        storage.getRuntime.mockReturnValue(
            of(
                buildPluginRuntime({
                    database: buildPluginRuntimeDatabase({
                        state: 'pending',
                        migrations: { applied: [], in_package: 1 },
                        size_bytes: null,
                        ready_at: null,
                    }),
                })
            )
        );
        render();

        expect(fact('Migrations')).toBe('0 of 1');
        expect(section('Database')!.querySelector('details')).toBeNull();
        expect(fact('Size')).toBe('—');
    });

    it('says when EpicStaff set the timeout back, and shows why setting the database up failed', () => {
        storage.getRuntime.mockReturnValue(
            of(
                buildPluginRuntime({
                    database: buildPluginRuntimeDatabase({
                        state: 'failed',
                        last_error: 'Migration 001_weather.sql failed: syntax error at or near "TABLEE"',
                        limits_restored_at: '2026-10-21T08:05:00Z',
                    }),
                })
            )
        );
        render();

        const database = section('Database')!;
        expect(text(database.querySelector('.runtime__callout'))).toMatch(
            /^Timeout restored at Oct 21, 2026, .+: the plugin changed its own default, and EpicStaff set it back\.$/
        );
        expect(text(database.querySelector('.runtime__error'))).toBe(
            'Migration 001_weather.sql failed: syntax error at or near "TABLEE"'
        );
    });

    it('lists the hosts the backend may reach, with their reasons', () => {
        storage.getRuntime.mockReturnValue(
            of(
                buildPluginRuntime({
                    egress: {
                        hosts: [
                            {
                                host: 'geocoding-api.open-meteo.com',
                                reason: 'Looks up places by name when someone adds a saved place.',
                            },
                        ],
                    },
                })
            )
        );
        render();

        const items = Array.from(section('Outbound access')!.querySelectorAll('li')).map((item) => [
            text(item.querySelector('code')),
            text(item.querySelector('span')),
        ]);
        expect(items).toEqual([
            ['geocoding-api.open-meteo.com', 'Looks up places by name when someone adds a saved place.'],
        ]);
    });

    it('says when the backend cannot reach the internet, and leaves out the database it does not have', () => {
        render();

        expect(sectionTitles()).toEqual(['Node', 'Process', 'Outbound access']);
        expect(text(section('Outbound access'))).toContain('None: the backend cannot reach the internet.');
    });

    it('leaves out both sections for a plugin with neither', () => {
        storage.getRuntime.mockReturnValue(of(buildPluginRuntime({ database: null, egress: null })));
        render();

        expect(sectionTitles()).toEqual(['Node', 'Process']);
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

    describe('during an upgrade', () => {
        /** The backups of Weather's failed upgrade to 0.7.1: its own, and one of the upgrade to 0.7.0 before it. */
        const BACKUPS = buildPluginBackupList({
            backups: [
                buildPluginBackup({
                    id: 62,
                    file_name: '20261021T110100Z-u8-pre_upgrade.dump',
                    version: '0.7.0',
                    upgrade: { id: 8, to_version: '0.7.1' },
                    created_at: '2026-10-21T11:01:00Z',
                    restorable: true,
                    not_restorable_reason: null,
                }),
                buildPluginBackup({ not_restorable_reason: 'earlier_upgrade' }),
            ],
        });

        function backupRows(): string[] {
            return Array.from(element.querySelectorAll('.backups__row')).map((row) => text(row));
        }

        function restoreButton(): HTMLButtonElement | undefined {
            return Array.from(element.querySelectorAll<HTMLButtonElement>('.backups__row button')).find(
                (button) => button.textContent?.trim() === 'Restore…'
            );
        }

        function showUpgrade(upgrade: PluginUpgrade | null): void {
            fixture.componentRef.setInput('openUpgrade', upgrade);
            fixture.detectChanges();
            TestBed.tick();
            fixture.detectChanges();
        }

        beforeEach(() => {
            storage.getRuntime.mockReturnValue(
                of(
                    buildPluginRuntime({
                        database: buildPluginRuntimeDatabase(),
                        upgrade: { from_version: '0.7.0', to_version: '0.7.1' },
                    })
                )
            );
            storage.listBackups.mockReturnValue(of(BACKUPS));
        });

        it('says the node runs the new version while it differs from the current one', () => {
            render();
            expect(text(element.querySelector('.runtime__upgrade'))).toBe('Running 0.7.0 → 0.7.1');

            storage.getRuntime.mockReturnValue(of(buildPluginRuntime({ database: buildPluginRuntimeDatabase() })));
            poll();
            expect(element.querySelector('.runtime__upgrade')).toBeNull();
        });

        it('lists the backups with what they hold, and Restore… only where the server allows it', () => {
            render();

            const rows = backupRows();
            expect(rows[0]).toMatch(/^Before upgrade to 0\.7\.1 holds 0\.7\.0 · .+ · Oct 21, 2026, .+ Restore…$/);
            expect(rows[1]).toMatch(
                /^Before upgrade to 0\.7\.0 holds 0\.6\.0 · .+ · .+ Not restorable: from an earlier upgrade$/
            );
            expect(element.querySelectorAll('.backups__row button')).toHaveLength(1);
        });

        it('names a backup taken before a restore', () => {
            storage.listBackups.mockReturnValue(
                of(
                    buildPluginBackupList({
                        backups: [
                            buildPluginBackup({
                                reason: 'pre_restore',
                                version: '0.7.1',
                                upgrade: { id: 8, to_version: '0.7.1' },
                                not_restorable_reason: 'not_now',
                            }),
                        ],
                    })
                )
            );
            render();

            expect(backupRows()[0]).toContain('Before restore · during the upgrade to 0.7.1');
            expect(backupRows()[0]).toContain('Not restorable: only while an upgrade has failed');
        });

        it('opens the restore dialog with the phrase the list carries, and tells the page once it is asked for', () => {
            openRestore.mockReturnValue(of(buildPluginRestore({ state: 'pending', step: null })));
            render();

            restoreButton()!.click();
            fixture.detectChanges();

            expect(openRestore).toHaveBeenCalledWith({
                identifier: 'weather',
                pluginName: 'Weather',
                databaseName: 'plugin_weather',
                backup: BACKUPS.backups[0],
                verificationPhrase: 'restore-weather',
            });
            expect(changes).toBe(1);
            expect(storage.listBackups).toHaveBeenCalledTimes(2);
        });

        it('loads the backups again when the open upgrade moves, not on every runtime poll', () => {
            render();
            expect(storage.listBackups).toHaveBeenCalledTimes(1);

            poll();
            expect(storage.listBackups).toHaveBeenCalledTimes(1);

            showUpgrade(buildFailedMigrationUpgrade());
            expect(storage.listBackups).toHaveBeenCalledTimes(2);

            showUpgrade(buildFailedMigrationUpgrade({ restore: buildPluginRestore() }));
            expect(storage.listBackups).toHaveBeenCalledTimes(3);

            showUpgrade(buildFailedMigrationUpgrade({ restore: buildPluginRestore() }));
            expect(storage.listBackups).toHaveBeenCalledTimes(3);
        });

        it('brings the backups into view when asked to', () => {
            // jsdom does not scroll; the panel calls it when the browser has it.
            const scrollIntoView = vi.fn();
            Object.defineProperty(Element.prototype, 'scrollIntoView', { value: scrollIntoView, configurable: true });
            onTestFinished(() => {
                delete (Element.prototype as Partial<Element>).scrollIntoView;
            });
            fixture = TestBed.createComponent(PluginRuntimePanelComponent);
            element = fixture.nativeElement as HTMLElement;
            fixture.componentRef.setInput('identifier', 'weather');
            fixture.componentRef.setInput('pluginName', 'Weather');
            fixture.componentRef.setInput('revealBackups', true);
            fixture.detectChanges();
            TestBed.tick();
            vi.advanceTimersByTime(0);
            fixture.detectChanges();
            TestBed.tick();

            expect(scrollIntoView).toHaveBeenCalledTimes(1);
            expect(document.activeElement?.textContent?.trim()).toBe('Backups');
        });

        it('says when the list could not be loaded, and loads it again on Retry', () => {
            storage.listBackups.mockReturnValueOnce(
                new Observable<PluginBackupList>((subscriber) => subscriber.error(new Error('offline')))
            );
            render();
            expect(text(element.querySelector('.backups__error'))).toContain("Couldn't load the backups.");

            Array.from(element.querySelectorAll<HTMLButtonElement>('.backups__error button'))[0].click();
            fixture.detectChanges();

            expect(element.querySelector('.backups__error')).toBeNull();
            expect(backupRows()).toHaveLength(2);
        });
    });
});
