import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';
import type { Mock } from 'vitest';

import { PluginDetail, PluginGrant } from '../../models/plugin-admin.model';
import { PluginDataFate, PluginGrantPurgePreview, PluginPurgePreview } from '../../models/plugin-purge-preview.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import {
    buildGrantPurgePreview,
    buildPluginDetail,
    buildPluginGrant,
    buildPluginPurgePreview,
} from '../../testing/plugin-fixtures';
import { PLUGIN_ERROR_MESSAGES } from '../../utils/plugin-error-message.util';
import {
    PLUGIN_PURGE_FLOWS_HINT,
    PluginPurgeDialogComponent,
    PluginPurgeDialogData,
    PluginPurgeDialogResult,
} from './plugin-purge-dialog.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const GRANT = buildPluginGrant();
const DELETING_GRANT: PluginGrant = { ...GRANT, state: 'purging', allowed_actions: [] };
const DELETING_PLUGIN: PluginDetail = buildPluginDetail({ state: 'purging', allowed_actions: [] });
const ORGANIZATION_FLOWS = 'Flows of this organization that use them';

function failure(status: number, code: string): HttpErrorResponse {
    return new HttpErrorResponse({ status, error: { status_code: status, code, message: 'Refused.' } });
}

describe('PluginPurgeDialogComponent', () => {
    let fixture: ComponentFixture<PluginPurgeDialogComponent>;
    let element: HTMLElement;
    let storage: {
        getGrantPurgePreview: Mock<(identifier: string, grantId: number) => Observable<PluginGrantPurgePreview>>;
        purgeGrant: Mock<(identifier: string, grantId: number, phrase: string) => Observable<PluginGrant>>;
        getPluginPurgePreview: Mock<(identifier: string) => Observable<PluginPurgePreview>>;
        purgePlugin: Mock<(identifier: string, phrase: string) => Observable<PluginDetail>>;
    };
    let dialogRef: {
        close: Mock<(result?: PluginPurgeDialogResult) => void>;
        keydownEvents: Subject<KeyboardEvent>;
    };

    function render(data: PluginPurgeDialogData): void {
        TestBed.overrideProvider(DIALOG_DATA, { useValue: data });
        fixture = TestBed.createComponent(PluginPurgeDialogComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    }

    function renderGrant(): void {
        render({ scope: 'grant', identifier: 'weather', pluginName: 'Weather', grant: GRANT });
    }

    function renderPlugin(): void {
        render({ scope: 'plugin', identifier: 'weather', pluginName: 'Weather' });
    }

    function text(node: Element | null | undefined): string {
        return node?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    }

    function button(label: string): HTMLButtonElement {
        return Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find(
            (candidate) => text(candidate) === label
        )!;
    }

    function sectionHeadings(): string[] {
        return Array.from(element.querySelectorAll('app-plugin-preview-section h3')).map((heading) => text(heading));
    }

    function section(heading: string): HTMLElement | undefined {
        return Array.from(element.querySelectorAll<HTMLElement>('app-plugin-preview-section')).find(
            (candidate) => text(candidate.querySelector('h3')) === heading
        );
    }

    /** Each line of a section's list as "name | detail". */
    function items(heading: string): string[] {
        return Array.from(section(heading)?.querySelectorAll('li') ?? []).map((item) =>
            [text(item.querySelector('.section__name')), text(item.querySelector('.section__detail'))]
                .filter(Boolean)
                .join(' | ')
        );
    }

    function type(phrase: string): void {
        const input = element.querySelector<HTMLInputElement>('.purge__verification-input')!;
        input.value = phrase;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        storage = {
            getGrantPurgePreview: vi.fn(() => of(buildGrantPurgePreview())),
            purgeGrant: vi.fn(() => of(DELETING_GRANT)),
            getPluginPurgePreview: vi.fn(() => of(buildPluginPurgePreview())),
            purgePlugin: vi.fn(() => of(DELETING_PLUGIN)),
        };
        dialogRef = { close: vi.fn(), keydownEvents: new Subject<KeyboardEvent>() };
        TestBed.configureTestingModule({
            imports: [PluginPurgeDialogComponent],
            providers: [
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: DIALOG_DATA, useValue: null },
                { provide: DialogRef, useValue: dialogRef },
            ],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    describe('for a grant', () => {
        it('loads the preview with a spinner, and asks for no phrase before it is there', () => {
            const preview = new Subject<PluginGrantPurgePreview>();
            storage.getGrantPurgePreview.mockReturnValue(preview);
            renderGrant();

            expect(storage.getGrantPurgePreview).toHaveBeenCalledWith('weather', GRANT.id);
            expect(element.querySelector('app-loading-spinner')).not.toBeNull();
            expect(text(element.querySelector('.dialog__title'))).toBe("Delete Weather's data in Acme now");
            expect(text(element.querySelector('.purge__summary'))).toBe(
                'This cannot be undone. Everything Weather owns in Acme is deleted, and nothing goes to the recycle bin.'
            );
            expect(element.querySelector('.purge__verification-input')).toBeNull();
            expect(button('Delete permanently').disabled).toBe(true);

            preview.next(buildGrantPurgePreview());
            preview.complete();
            fixture.detectChanges();

            expect(element.querySelector('app-loading-spinner')).toBeNull();
            expect(text(element.querySelector('.purge__verification-label'))).toBe(
                'Type purge-weather-Acme to confirm'
            );
        });

        it('shows every section, in order: owned, the organization flows, the own flows, sessions, default models', () => {
            renderGrant();

            expect(sectionHeadings()).toEqual([
                'What Weather owns in Acme',
                ORGANIZATION_FLOWS,
                "Weather's own flows",
                'Running sessions that will be stopped',
                'Default-model settings that will be cleared',
            ]);
            expect(items('What Weather owns in Acme')).toEqual([
                'Files | 1',
                'Flows | 1',
                'LLM configs | 1',
                'Secrets | 1',
            ]);
            expect(items(ORGANIZATION_FLOWS)).toEqual(['Daily digest']);
            expect(section(ORGANIZATION_FLOWS)?.querySelector('.section--emphasised')).not.toBeNull();
            expect(text(section(ORGANIZATION_FLOWS)?.querySelector('.section__hint'))).toBe(PLUGIN_PURGE_FLOWS_HINT);
            expect(items("Weather's own flows")).toEqual(['Weather forecast']);
            expect(items('Running sessions that will be stopped')[0]).toMatch(/^Daily digest \| Running · started /);
            expect(items('Default-model settings that will be cleared')).toEqual(['Agent LLM → Weather summaries']);
            expect(text(element.querySelector('.purge__plugin-data'))).toBe('Weather deletes its own data for Acme.');
        });

        it.each<[PluginDataFate, string | null]>([
            ['deleted_by_plugin', 'Weather deletes its own data for Acme.'],
            ['kept_until_plugin_deleted', "Weather's own data for Acme stays until Weather is deleted."],
            ['none', null],
        ])("says what becomes of the plugin's own data when it is %s", (fate, expected) => {
            storage.getGrantPurgePreview.mockReturnValue(of(buildGrantPurgePreview({ plugin_data: fate })));
            renderGrant();

            const line = element.querySelector('.purge__plugin-data');
            if (expected === null) expect(line).toBeNull();
            else expect(text(line)).toBe(expected);
        });

        it('says when nothing is owned and no flow of the organization uses it, and leaves out empty lists', () => {
            storage.getGrantPurgePreview.mockReturnValue(
                of(
                    buildGrantPurgePreview({
                        grant: { id: 5, state: 'suspended' },
                        owned_resources: [],
                        flows: { organization: { total: 0, items: [] }, plugin: { total: 0, items: [] } },
                        running_sessions: { total: 0, items: [] },
                        default_models: [],
                    })
                )
            );
            renderGrant();

            expect(sectionHeadings()).toEqual(['What Weather owns in Acme', ORGANIZATION_FLOWS]);
            expect(text(section('What Weather owns in Acme')?.querySelector('.section__empty'))).toBe(
                'Nothing. Weather owns nothing in Acme.'
            );
            expect(text(section(ORGANIZATION_FLOWS)?.querySelector('.section__empty'))).toBe(
                'None. No flow of Acme uses anything Weather owns.'
            );
            expect(section(ORGANIZATION_FLOWS)?.querySelector('.section__hint')).toBeNull();
        });

        it('says how many more the server counted than it sent', () => {
            storage.getGrantPurgePreview.mockReturnValue(
                of(
                    buildGrantPurgePreview({
                        flows: {
                            organization: { total: 103, items: [{ id: 21, name: 'Daily digest' }] },
                            plugin: { total: 1, items: [{ id: 18, name: 'Weather forecast' }] },
                        },
                    })
                )
            );
            renderGrant();

            expect(text(section(ORGANIZATION_FLOWS)?.querySelector('.section__more'))).toBe('and 102 more');
        });

        it('shows why the preview did not load, and loads it again on Retry', () => {
            storage.getGrantPurgePreview.mockReturnValueOnce(throwError(() => failure(404, 'grant_not_found')));
            renderGrant();

            expect(text(element.querySelector('.dialog__load-error'))).toContain(PLUGIN_ERROR_MESSAGES.grant_not_found);
            expect(element.querySelector('.purge__verification-input')).toBeNull();
            expect(button('Delete permanently').disabled).toBe(true);

            button('Retry').click();
            fixture.detectChanges();

            expect(storage.getGrantPurgePreview).toHaveBeenCalledTimes(2);
            expect(element.querySelector('.dialog__load-error')).toBeNull();
            expect(items(ORGANIZATION_FLOWS)).toEqual(['Daily digest']);
        });

        it.each(['', 'purge-weather-acme', 'Purge-weather-Acme', 'purge-weather-Acme ', ' purge-weather-Acme'])(
            'keeps Delete permanently disabled for %j',
            (typed) => {
                renderGrant();
                type(typed);

                expect(button('Delete permanently').disabled).toBe(true);
                button('Delete permanently').click();
                expect(storage.purgeGrant).not.toHaveBeenCalled();
            }
        );

        it('deletes once the phrase is typed exactly, sends it as typed and closes with the grant', () => {
            renderGrant();
            type('purge-weather-Acme');

            expect(button('Delete permanently').disabled).toBe(false);
            button('Delete permanently').click();

            expect(storage.purgeGrant).toHaveBeenCalledWith('weather', GRANT.id, 'purge-weather-Acme');
            expect(dialogRef.close).toHaveBeenCalledWith({ scope: 'grant', grant: DELETING_GRANT });
        });

        it('keeps the dialog open when the phrase no longer matches, and loads the preview again', () => {
            storage.purgeGrant.mockReturnValue(throwError(() => failure(400, 'invalid_purge_phrase')));
            storage.getGrantPurgePreview
                .mockReturnValueOnce(of(buildGrantPurgePreview()))
                .mockReturnValue(of(buildGrantPurgePreview({ verification_phrase: 'purge-weather-Acme Corp' })));
            renderGrant();
            type('purge-weather-Acme');

            button('Delete permanently').click();
            fixture.detectChanges();

            expect(dialogRef.close).not.toHaveBeenCalled();
            expect(text(element.querySelector('.dialog__error'))).toBe(PLUGIN_ERROR_MESSAGES.invalid_purge_phrase);
            expect(storage.getGrantPurgePreview).toHaveBeenCalledTimes(2);
            expect(text(element.querySelector('.purge__verification-label'))).toBe(
                'Type purge-weather-Acme Corp to confirm'
            );
            expect(button('Delete permanently').disabled).toBe(true);
        });

        it('keeps the dialog open with the reason for another refusal, without loading the preview again', () => {
            storage.purgeGrant.mockReturnValue(throwError(() => failure(409, 'grant_not_purgeable')));
            renderGrant();
            type('purge-weather-Acme');

            button('Delete permanently').click();
            fixture.detectChanges();

            expect(dialogRef.close).not.toHaveBeenCalled();
            expect(text(element.querySelector('.dialog__error'))).toBe(PLUGIN_ERROR_MESSAGES.grant_not_purgeable);
            expect(storage.getGrantPurgePreview).toHaveBeenCalledTimes(1);
        });

        it('closes on Cancel and on Escape without a call, but not while the deletion is being asked for', () => {
            renderGrant();

            button('Cancel').click();
            expect(dialogRef.close).toHaveBeenCalledWith();
            expect(storage.purgeGrant).not.toHaveBeenCalled();

            dialogRef.keydownEvents.next(new KeyboardEvent('keydown', { key: 'Escape' }));
            expect(dialogRef.close).toHaveBeenCalledTimes(2);

            const pending = new Subject<PluginGrant>();
            storage.purgeGrant.mockReturnValue(pending);
            type('purge-weather-Acme');
            button('Delete permanently').click();
            fixture.detectChanges();

            dialogRef.keydownEvents.next(new KeyboardEvent('keydown', { key: 'Escape' }));
            button('Cancel').click();
            expect(dialogRef.close).toHaveBeenCalledTimes(2);
            expect(button('Cancel').disabled).toBe(true);
        });
    });

    describe('for a plugin', () => {
        it('shows the organizations, the owned totals, the hook, what is deleted, and asks for the phrase', () => {
            renderPlugin();

            expect(storage.getPluginPurgePreview).toHaveBeenCalledWith('weather');
            expect(text(element.querySelector('.dialog__title'))).toBe('Delete Weather permanently');
            expect(text(element.querySelector('.purge__summary'))).toBe(
                'This cannot be undone. Weather is deleted from every organization, with everything it owns. ' +
                    'Nothing goes to the recycle bin.'
            );
            expect(sectionHeadings()).toEqual(['Organizations', 'What Weather owns in all organizations']);
            expect(items('Organizations')).toEqual(['Acme | Active · 2 owned']);
            expect(items('What Weather owns in all organizations')).toEqual(['Files | 1', 'Flows | 1']);
            expect(text(element.querySelector('.purge__hook'))).toBe(
                'Weather first deletes its own data for each organization.'
            );
            expect(text(element.querySelector('.purge__removal'))).toBe(
                'Then the plugin node deletes its database plugin_weather (7.3 MB) and its files, and EpicStaff ' +
                    'deletes its frontend and package files. No backup is taken.'
            );
            expect(element.querySelector('.purge__open-removals')).toBeNull();
            expect(text(element.querySelector('.purge__verification-label'))).toBe('Type purge-weather to confirm');
        });

        it('says how many data removals are still waiting, and how many more organizations there are', () => {
            storage.getPluginPurgePreview.mockReturnValue(
                of(
                    buildPluginPurgePreview({
                        organizations: {
                            total: 4,
                            items: [
                                {
                                    grant_id: 5,
                                    organization: { id: 3, name: 'Acme' },
                                    state: 'suspended',
                                    owned_resource_count: 0,
                                },
                            ],
                        },
                        data_removals_open: 2,
                    })
                )
            );
            renderPlugin();

            expect(items('Organizations')).toEqual(['Acme | Suspended · 0 owned']);
            expect(text(section('Organizations')?.querySelector('.section__more'))).toBe('and 3 more');
            expect(text(element.querySelector('.purge__open-removals'))).toBe('2 data removals are still waiting.');
        });

        it.each<[Partial<PluginPurgePreview>, string]>([
            [
                { database: null },
                'Then the plugin node deletes its files, and EpicStaff deletes its frontend and package files. ' +
                    'No backup is taken.',
            ],
            [
                { database: { name: 'plugin_weather', size_bytes: null } },
                'Then the plugin node deletes its database plugin_weather and its files, and EpicStaff deletes its ' +
                    'frontend and package files. No backup is taken.',
            ],
            [
                { has_backend: false, database: null },
                'Then EpicStaff deletes its frontend and package files. No backup is taken.',
            ],
            [
                { has_spa: false },
                'Then the plugin node deletes its database plugin_weather (7.3 MB) and its files, and EpicStaff ' +
                    'deletes its package files. No backup is taken.',
            ],
        ])('leaves out what the plugin does not have (%j)', (overrides, expected) => {
            storage.getPluginPurgePreview.mockReturnValue(of(buildPluginPurgePreview(overrides)));
            renderPlugin();

            expect(text(element.querySelector('.purge__removal'))).toBe(expected);
        });

        it('says nothing about its own data without an organization removed hook', () => {
            storage.getPluginPurgePreview.mockReturnValue(
                of(buildPluginPurgePreview({ has_org_removed_hook: false, data_removals_open: 1 }))
            );
            renderPlugin();

            expect(element.querySelector('.purge__hook')).toBeNull();
            expect(text(element.querySelector('.purge__open-removals'))).toBe('1 data removal is still waiting.');
        });

        it.each(['purge-weather ', 'Purge-weather', 'purge-Weather'])(
            'keeps Delete permanently disabled for %j',
            (typed) => {
                renderPlugin();
                type(typed);

                expect(button('Delete permanently').disabled).toBe(true);
            }
        );

        it('deletes once the phrase is typed exactly and closes with the plugin', () => {
            renderPlugin();
            type('purge-weather');
            button('Delete permanently').click();

            expect(storage.purgePlugin).toHaveBeenCalledWith('weather', 'purge-weather');
            expect(dialogRef.close).toHaveBeenCalledWith({ scope: 'plugin', plugin: DELETING_PLUGIN });
        });

        it('keeps the dialog open when the phrase is refused, and loads the preview again', () => {
            storage.purgePlugin.mockReturnValue(throwError(() => failure(400, 'invalid_purge_phrase')));
            renderPlugin();
            type('purge-weather');

            button('Delete permanently').click();
            fixture.detectChanges();

            expect(dialogRef.close).not.toHaveBeenCalled();
            expect(text(element.querySelector('.dialog__error'))).toBe(PLUGIN_ERROR_MESSAGES.invalid_purge_phrase);
            expect(storage.getPluginPurgePreview).toHaveBeenCalledTimes(2);
        });

        it('makes no call on Cancel', () => {
            renderPlugin();
            type('purge-weather');

            button('Cancel').click();

            expect(storage.purgePlugin).not.toHaveBeenCalled();
            expect(dialogRef.close).toHaveBeenCalledWith();
        });
    });
});
