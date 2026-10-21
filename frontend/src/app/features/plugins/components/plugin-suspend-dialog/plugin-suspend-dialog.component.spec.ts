import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';
import type { Mock } from 'vitest';

import { DEFAULT_LLMS_SECTIONS } from '../../../configure-models/constants/default-llms-sections.constant';
import { PluginGrant } from '../../models/plugin-admin.model';
import { PluginDefaultModelSetting, PluginSuspendPreview } from '../../models/plugin-suspend-preview.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildPluginGrant, buildSuspendPreview } from '../../testing/plugin-fixtures';
import {
    PLUGIN_DEFAULT_MODEL_SETTING_LABELS,
    PLUGIN_DEFAULT_MODEL_SETTINGS_ON_SETTINGS_PAGE,
} from '../../utils/plugin-display.util';
import { PLUGIN_ERROR_MESSAGES } from '../../utils/plugin-error-message.util';
import { PluginSuspendDialogComponent, PluginSuspendDialogData } from './plugin-suspend-dialog.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const GRANT = buildPluginGrant();
const SUSPENDED: PluginGrant = {
    ...GRANT,
    state: 'suspended',
    allowed_actions: ['resume'],
    suspended_at: '2026-10-21T09:00:00Z',
    purge_after: '2026-11-20T09:00:00Z',
};
const ORGANIZATION_FLOWS = 'Flows of this organization that will stop';
const DEFAULT_MODELS = "Default-model settings that use Weather's configs";
const BASE_HINT = 'New agents and features outside runs, such as the flow assistant, keep using these settings.';
const REPOINT_HINT = 'Repoint them in Settings → Default LLMs.';
const SETTINGS_ON_THE_PAGE: PluginDefaultModelSetting[] = ['agent_llm_config', 'agent_fcm_llm_config'];
const SETTINGS_WITHOUT_A_PAGE: PluginDefaultModelSetting[] = [
    'voice_llm_config',
    'transcription_llm_config',
    'project_manager_llm_config',
    'memory_embedding_config',
    'memory_llm_config',
];
const EVERY_DEFAULT_MODEL_SETTING = [...SETTINGS_ON_THE_PAGE, ...SETTINGS_WITHOUT_A_PAGE];

describe('PluginSuspendDialogComponent', () => {
    let fixture: ComponentFixture<PluginSuspendDialogComponent>;
    let element: HTMLElement;
    let storage: {
        getSuspendPreview: Mock<(identifier: string, grantId: number) => Observable<PluginSuspendPreview>>;
        suspendGrant: Mock<(identifier: string, grantId: number) => Observable<PluginGrant>>;
    };
    let dialogRef: { close: Mock<(result?: PluginGrant) => void> };

    function render(): void {
        fixture = TestBed.createComponent(PluginSuspendDialogComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
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

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        storage = {
            getSuspendPreview: vi.fn(() => of(buildSuspendPreview())),
            suspendGrant: vi.fn(() => of(SUSPENDED)),
        };
        dialogRef = { close: vi.fn() };
        const data: PluginSuspendDialogData = { identifier: 'weather', pluginName: 'Weather', grant: GRANT };
        TestBed.configureTestingModule({
            imports: [PluginSuspendDialogComponent],
            providers: [
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: DIALOG_DATA, useValue: data },
                { provide: DialogRef, useValue: dialogRef },
            ],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('waits for the preview with a spinner, and Suspend waits with it', () => {
        const preview = new Subject<PluginSuspendPreview>();
        storage.getSuspendPreview.mockReturnValue(preview);
        render();

        expect(storage.getSuspendPreview).toHaveBeenCalledWith('weather', GRANT.id);
        expect(element.querySelector('app-loading-spinner')).not.toBeNull();
        expect(button('Suspend').disabled).toBe(true);
        expect(text(element.querySelector('.dialog__title'))).toBe('Suspend Weather in Acme');
        expect(text(element.querySelector('.suspend__summary'))).toContain('Weather will stop working in Acme.');

        preview.next(buildSuspendPreview());
        preview.complete();
        fixture.detectChanges();

        expect(element.querySelector('app-loading-spinner')).toBeNull();
        expect(button('Suspend').disabled).toBe(false);
    });

    it('says why the preview did not load, and loads it again on Retry', () => {
        storage.getSuspendPreview.mockReturnValueOnce(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 404,
                        error: { status_code: 404, code: 'grant_not_found', message: 'Not found.' },
                    })
            )
        );
        render();

        expect(text(element.querySelector('.suspend__load-error'))).toContain(PLUGIN_ERROR_MESSAGES.grant_not_found);
        expect(sectionHeadings()).toEqual([]);

        button('Retry').click();
        fixture.detectChanges();

        expect(storage.getSuspendPreview).toHaveBeenCalledTimes(2);
        expect(element.querySelector('.suspend__load-error')).toBeNull();
        expect(items(ORGANIZATION_FLOWS)).toEqual(['Daily digest']);
    });

    it('still suspends when the preview did not load', () => {
        storage.getSuspendPreview.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 500 })));
        render();

        button('Suspend').click();

        expect(storage.suspendGrant).toHaveBeenCalledWith('weather', GRANT.id);
        expect(dialogRef.close).toHaveBeenCalledWith(SUSPENDED);
    });

    it('shows every section in order, and when the data is kept until', () => {
        storage.getSuspendPreview.mockReturnValue(
            of(
                buildSuspendPreview({
                    realtime_agents: { total: 1, items: [{ id: 2, name: 'Forecast caller' }] },
                    voice_channels: { total: 1, items: [{ id: 3, name: 'Front desk line' }] },
                })
            )
        );
        render();

        expect(sectionHeadings()).toEqual([
            'What Weather owns in Acme',
            ORGANIZATION_FLOWS,
            "Weather's own flows",
            'Running sessions that will be stopped',
            'Triggers that will be refused',
            'Realtime agents that will be refused',
            'Voice channels that will be refused',
            "Default-model settings that use Weather's configs",
        ]);
        expect(items('What Weather owns in Acme')).toEqual([
            'Files | 1',
            'Flows | 1',
            'LLM configs | 1',
            'Secrets | 1',
        ]);
        expect(items('Running sessions that will be stopped')).toEqual([
            expect.stringMatching(/^Daily digest \| Running · started .+ ago$/),
        ]);
        expect(items('Triggers that will be refused')).toEqual(['Daily digest | Schedule: Every 2 minutes']);
        expect(items('Realtime agents that will be refused')).toEqual(['Forecast caller']);
        expect(items('Voice channels that will be refused')).toEqual(['Front desk line']);
        expect(text(element.querySelector('.suspend__kept'))).toBe(
            'Data kept until Nov 20, 2026. Resuming before then restores everything.'
        );
    });

    it("keeps the organization's flows apart from the plugin's own, and emphasises them", () => {
        render();

        expect(items(ORGANIZATION_FLOWS)).toEqual(['Daily digest']);
        expect(items("Weather's own flows")).toEqual(['Weather forecast']);
        expect(section(ORGANIZATION_FLOWS)?.querySelector('.section--emphasised')).not.toBeNull();
        expect(section("Weather's own flows")?.querySelector('.section--emphasised')).toBeNull();
    });

    it("says when none of the organization's flows stops, and leaves out the other empty sections", () => {
        storage.getSuspendPreview.mockReturnValue(
            of(
                buildSuspendPreview({
                    owned_resources: [],
                    flows: { organization: { total: 0, items: [] }, plugin: { total: 0, items: [] } },
                    running_sessions: { total: 0, items: [] },
                    triggers: { total: 0, items: [] },
                    default_models: [],
                })
            )
        );
        render();

        expect(sectionHeadings()).toEqual([ORGANIZATION_FLOWS]);
        expect(text(section(ORGANIZATION_FLOWS)?.querySelector('.section__empty'))).toBe(
            'None. No flow of Acme uses anything Weather owns.'
        );
        expect(text(element.querySelector('.suspend__kept'))).toContain('Data kept until Nov 20, 2026');
    });

    it('ends a list cut short with how many more there are', () => {
        const flows = Array.from({ length: 100 }, (_, index) => ({ id: index + 1, name: `Flow ${index + 1}` }));
        storage.getSuspendPreview.mockReturnValue(
            of(
                buildSuspendPreview({
                    flows: { organization: { total: 101, items: flows }, plugin: { total: 1, items: [flows[0]] } },
                })
            )
        );
        render();

        expect(items(ORGANIZATION_FLOWS)).toHaveLength(100);
        expect(text(section(ORGANIZATION_FLOWS)?.querySelector('.section__more'))).toBe('and 1 more');
        expect(section("Weather's own flows")?.querySelector('.section__more')).toBeNull();
    });

    function renderDefaultModels(settings: readonly PluginDefaultModelSetting[]): void {
        storage.getSuspendPreview.mockReturnValue(
            of(
                buildSuspendPreview({
                    default_models: settings.map((setting, index) => ({
                        setting,
                        config: { id: index + 1, name: 'Weather summaries' },
                    })),
                })
            )
        );
        render();
    }

    it('names the default-model settings as the settings page does', () => {
        renderDefaultModels(EVERY_DEFAULT_MODEL_SETTING);

        expect(items(DEFAULT_MODELS)).toEqual([
            'Agent LLM → Weather summaries',
            'Agent Function Calling LLM → Weather summaries',
            'Voice LLM → Weather summaries',
            'Transcription LLM → Weather summaries',
            'Project Manager LLM → Weather summaries',
            'Memory Embedding Model → Weather summaries',
            'Memory LLM → Weather summaries',
        ]);
    });

    it.each<{ listed: string; settings: readonly PluginDefaultModelSetting[]; hint: string }>([
        { listed: 'only agent settings', settings: SETTINGS_ON_THE_PAGE, hint: `${BASE_HINT} ${REPOINT_HINT}` },
        { listed: 'only settings without a page', settings: SETTINGS_WITHOUT_A_PAGE, hint: BASE_HINT },
        {
            listed: 'agent settings and settings without a page',
            settings: ['voice_llm_config', 'agent_fcm_llm_config', 'memory_llm_config'],
            hint: `${BASE_HINT} ${REPOINT_HINT}`,
        },
    ])('points to the settings page only when it can change one of them: $listed', ({ settings, hint }) => {
        renderDefaultModels(settings);

        expect(items(DEFAULT_MODELS)).toHaveLength(settings.length);
        expect(text(section(DEFAULT_MODELS)?.querySelector('.section__hint'))).toBe(hint);
    });

    it('uses the titles of the Default LLMs settings page, and knows which settings it shows', () => {
        const cards = DEFAULT_LLMS_SECTIONS.flatMap((pageSection) => pageSection.cards);
        expect(cards.length).toBeGreaterThan(0);

        for (const card of cards) {
            expect(PLUGIN_DEFAULT_MODEL_SETTING_LABELS[card.field as PluginDefaultModelSetting]).toBe(card.title);
        }
        expect([...PLUGIN_DEFAULT_MODEL_SETTINGS_ON_SETTINGS_PAGE].sort()).toEqual(
            cards.map((card) => card.field).sort()
        );
    });

    it('suspends on confirm and closes with the suspended grant', () => {
        render();

        button('Suspend').click();

        expect(storage.suspendGrant).toHaveBeenCalledWith('weather', GRANT.id);
        expect(dialogRef.close).toHaveBeenCalledWith(SUSPENDED);
    });

    it('closes without a request on Cancel and on the close button', () => {
        render();

        button('Cancel').click();
        element.querySelector<HTMLButtonElement>('.dialog__close')!.click();

        expect(storage.suspendGrant).not.toHaveBeenCalled();
        expect(dialogRef.close).toHaveBeenCalledTimes(2);
        expect(dialogRef.close).toHaveBeenCalledWith();
    });

    it('stays open with the reason when the suspension is refused', () => {
        storage.suspendGrant.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 409,
                        error: { status_code: 409, code: 'grant_not_suspendable', message: 'Not suspendable.' },
                    })
            )
        );
        render();

        button('Suspend').click();
        fixture.detectChanges();

        expect(dialogRef.close).not.toHaveBeenCalled();
        expect(text(element.querySelector('.dialog__error'))).toBe(PLUGIN_ERROR_MESSAGES.grant_not_suspendable);
        expect(button('Suspend').disabled).toBe(false);
    });

    it('cannot be closed or suspended twice while the suspension is under way', () => {
        const answer = new Subject<PluginGrant>();
        storage.suspendGrant.mockReturnValue(answer);
        render();

        button('Suspend').click();
        fixture.detectChanges();

        expect(button('Suspend').disabled).toBe(true);
        expect(button('Cancel').disabled).toBe(true);
        expect(element.querySelector<HTMLButtonElement>('.dialog__close')!.disabled).toBe(true);
        button('Suspend').click();
        expect(storage.suspendGrant).toHaveBeenCalledTimes(1);

        answer.next(SUSPENDED);
        expect(dialogRef.close).toHaveBeenCalledWith(SUSPENDED);
    });
});
