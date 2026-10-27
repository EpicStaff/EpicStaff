import { OverlayContainer } from '@angular/cdk/overlay';
import { signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FullLLMConfig, FullLLMConfigService, FullRealtimeConfigService } from '@shared/services';
import { of } from 'rxjs';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { LlmModelSelectorComponent } from './llm-model-selector.component';

function config(id: number, modelName: string): FullLLMConfig {
    return { id, custom_name: '', modelDetails: { name: modelName }, providerDetails: null } as FullLLMConfig;
}

const CONFIGS = [config(1, 'gpt-primary'), config(2, 'claude-backup'), config(3, 'gemini-extra')];

function render(): {
    fixture: ComponentFixture<LlmModelSelectorComponent>;
    configs: WritableSignal<FullLLMConfig[]>;
    overlay: HTMLElement;
} {
    const configs = signal(CONFIGS);
    TestBed.configureTestingModule({
        providers: [
            {
                provide: FullLLMConfigService,
                useValue: { fullLLMConfigs: configs, getFullLLMConfigs: () => of(CONFIGS) },
            },
            { provide: FullRealtimeConfigService, useValue: {} },
            { provide: PermissionsService, useValue: { active: signal(null), can: () => true, canAny: () => true } },
        ],
    });
    const fixture = TestBed.createComponent(LlmModelSelectorComponent);
    fixture.detectChanges();
    return { fixture, configs, overlay: TestBed.inject(OverlayContainer).getContainerElement() };
}

function openDropdown(fixture: ComponentFixture<LlmModelSelectorComponent>): void {
    fixture.nativeElement.querySelector('.selected-model').click();
    fixture.detectChanges();
}

function optionNames(overlay: HTMLElement): string[] {
    return Array.from(overlay.querySelectorAll('.models-list .model-name')).map((el) => el.textContent?.trim() ?? '');
}

describe('LlmModelSelectorComponent excludedConfigId', () => {
    it('offers every config when nothing is excluded', () => {
        const { fixture, overlay } = render();

        openDropdown(fixture);

        expect(optionNames(overlay)).toEqual(['gpt-primary', 'claude-backup', 'gemini-extra']);
    });

    it('leaves the excluded config out of the options', () => {
        const { fixture, overlay } = render();
        fixture.componentRef.setInput('excludedConfigId', 1);

        openDropdown(fixture);

        expect(optionNames(overlay)).toEqual(['claude-backup', 'gemini-extra']);
    });

    it('still shows the excluded config when it is the current selection', () => {
        const { fixture } = render();
        fixture.componentInstance.writeValue(1);
        fixture.componentRef.setInput('excludedConfigId', 1);
        fixture.detectChanges();

        expect(fixture.nativeElement.querySelector('.selected-model .model-name').textContent).toContain('gpt-primary');
    });
});

describe('LlmModelSelectorComponent Clear', () => {
    it('emits modelSelected, so a consumer that autosaves on selection also saves a cleared value', () => {
        const { fixture, overlay } = render();
        const onChange = vi.fn();
        const emitted: unknown[] = [];
        fixture.componentInstance.registerOnChange(onChange);
        fixture.componentInstance.modelSelected.subscribe((id) => emitted.push(id));
        fixture.componentInstance.writeValue(2);
        fixture.detectChanges();

        openDropdown(fixture);
        overlay.querySelector<HTMLElement>('.deselect-option')!.click();

        expect(onChange).toHaveBeenCalledWith(null);
        expect(emitted).toEqual([undefined]);
    });
});
