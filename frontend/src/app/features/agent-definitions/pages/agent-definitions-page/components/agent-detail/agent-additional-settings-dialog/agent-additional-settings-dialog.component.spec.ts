import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';

import {
    AgentAdditionalSettingsData,
    AgentAdditionalSettingsDialogComponent,
    AgentAdditionalSettingsResult,
} from './agent-additional-settings-dialog.component';

// jsdom has no ResizeObserver; the buttons' collapse directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const STORED: AgentAdditionalSettingsData = {
    fcm_llm_config: null,
    openai_config: null,
    elevenlabs_config: null,
    gemini_config: null,
    voice: null,
    max_iter: 20,
    max_rpm: 10,
    max_execution_time: 60,
    max_retry_limit: 2,
    prompt_caching_enabled: false,
    promptCachingAvailable: true,
    max_tool_calls: 15,
    tool_timeout: 300,
    max_consecutive_failures: 3,
    schema_max_retries: 2,
};

describe('AgentAdditionalSettingsDialogComponent prompt caching', () => {
    let fixture: ComponentFixture<AgentAdditionalSettingsDialogComponent>;
    let closedWith: (AgentAdditionalSettingsResult | undefined)[];

    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    // The settings lists load over HTTP and stay unanswered: only the form is under test.
    function open(data: AgentAdditionalSettingsData): HTMLElement {
        closedWith = [];
        TestBed.configureTestingModule({
            imports: [AgentAdditionalSettingsDialogComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                {
                    provide: DialogRef,
                    useValue: {
                        close: (result?: AgentAdditionalSettingsResult) => closedWith.push(result),
                        keydownEvents: new Subject<KeyboardEvent>(),
                    },
                },
                { provide: DIALOG_DATA, useValue: data },
            ],
        });
        fixture = TestBed.createComponent(AgentAdditionalSettingsDialogComponent);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    function tabLabels(host: HTMLElement): string[] {
        return Array.from(host.querySelectorAll('app-tab-button'), (tab) => tab.textContent!.trim());
    }

    function openAdvancedTab(host: HTMLElement): void {
        Array.from(host.querySelectorAll<HTMLElement>('app-tab-button'))
            .find((tab) => tab.textContent!.trim() === 'Advanced')!
            .click();
        fixture.detectChanges();
    }

    function promptCachingSwitch(host: HTMLElement): HTMLInputElement | null {
        return host.querySelector<HTMLInputElement>('input[aria-label="Prompt Caching"]');
    }

    function clickSave(host: HTMLElement): void {
        Array.from(host.querySelectorAll<HTMLElement>('app-button'))
            .find((button) => button.textContent!.includes('Save Changes'))!
            .click();
    }

    it('offers no Advanced tab and no prompt caching switch when the models cannot use it', () => {
        const host = open({ ...STORED, promptCachingAvailable: false });

        expect(tabLabels(host)).not.toContain('Advanced');
        expect(promptCachingSwitch(host)).toBeNull();
    });

    it('lets the user switch prompt caching on and saves it', () => {
        const host = open(STORED);
        openAdvancedTab(host);
        const toggle = promptCachingSwitch(host)!;

        expect(toggle.disabled).toBe(false);
        expect(toggle.checked).toBe(false);
        toggle.click();
        fixture.detectChanges();
        expect(toggle.checked).toBe(true);

        clickSave(host);
        expect(closedWith).toHaveLength(1);
        expect(closedWith[0]!.prompt_caching_enabled).toBe(true);
        expect(closedWith[0]).not.toHaveProperty('cache');
    });

    it('keeps a stored setting while the switch is hidden', () => {
        const host = open({ ...STORED, prompt_caching_enabled: true, promptCachingAvailable: false });

        clickSave(host);

        expect(closedWith[0]!.prompt_caching_enabled).toBe(true);
    });
});
