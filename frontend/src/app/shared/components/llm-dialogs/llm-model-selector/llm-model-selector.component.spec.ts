import { Dialog } from '@angular/cdk/dialog';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { LLMModel, LLMProvider, ModelTypes } from '@shared/models';
import { LLMLibraryService, ProviderWithModels } from '@shared/services';
import { of } from 'rxjs';

import { CreateLlmModelModalComponent } from '../create-llm-model-modal/create-llm-model-modal.component';
import { LlmModelSelectorComponent } from './llm-model-selector.component';

function model(id: number, name: string, overrides: Partial<LLMModel> = {}): LLMModel {
    return { id, name, is_visible: true, is_custom: false, predefined: false, ...overrides } as LLMModel;
}

const ZETA: LLMProvider = { id: 1, name: 'Zeta' };
const ANTHROPIC: LLMProvider = { id: 2, name: 'Anthropic' };
const OPENAI: LLMProvider = { id: 3, name: 'OpenAI' };

const GROUPS: ProviderWithModels<LLMModel>[] = [
    { provider: ZETA, models: [model(10, 'zeta-small')] },
    { provider: ANTHROPIC, models: [model(20, 'claude-old', { predefined: true, is_visible: false })] },
    {
        provider: OPENAI,
        models: [
            model(30, 'gpt-a'),
            model(31, 'gpt-b', { is_custom: true }),
            model(32, 'gpt-c'),
            model(33, 'gpt-d'),
            model(34, 'gpt-e'),
        ],
    },
];

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function render(): {
    fixture: ComponentFixture<LlmModelSelectorComponent>;
    dialogOpen: ReturnType<typeof vi.fn>;
} {
    const dialogOpen = vi.fn(() => ({ closed: of(undefined) }));
    TestBed.configureTestingModule({
        providers: [
            { provide: LLMLibraryService, useValue: { loadModels: () => of(GROUPS) } },
            { provide: Dialog, useValue: { open: dialogOpen } },
        ],
    });
    const fixture = TestBed.createComponent(LlmModelSelectorComponent);
    fixture.componentRef.setInput('provider', ModelTypes.LLM);
    fixture.componentRef.setInput('placeholder', 'Select provider');
    fixture.detectChanges();
    return { fixture, dialogOpen };
}

function trigger(fixture: ComponentFixture<LlmModelSelectorComponent>): HTMLButtonElement {
    return (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('button[aria-expanded]')!;
}

function openOverlay(fixture: ComponentFixture<LlmModelSelectorComponent>): void {
    trigger(fixture).click();
    fixture.detectChanges();
}

function overlayButton(text: string): HTMLButtonElement | undefined {
    return Array.from(document.querySelectorAll<HTMLButtonElement>('.cdk-overlay-container button')).find(
        (button) => button.textContent!.trim() === text
    );
}

function overlayText(): string {
    return document.querySelector('.cdk-overlay-container')!.textContent!;
}

describe('LlmModelSelectorComponent', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('lists the top providers first, then the rest by name, collapsing a long provider to 3 models', () => {
        const { fixture } = render();

        openOverlay(fixture);
        const text = overlayText();

        expect(text.indexOf('OPENAI')).toBeLessThan(text.indexOf('ANTHROPIC'));
        expect(text.indexOf('ANTHROPIC')).toBeLessThan(text.indexOf('ZETA'));
        expect(overlayButton('gpt-c')).toBeDefined();
        expect(overlayButton('gpt-d')).toBeUndefined();
        expect(text).toContain('2 more');

        overlayButton('2 more')!.click();
        fixture.detectChanges();

        expect(overlayButton('gpt-e')).toBeDefined();
    });

    it('reports a picked model to the form and to modelChanged, and shows it on the trigger', () => {
        const { fixture } = render();
        const onChange = vi.fn();
        const changed = vi.fn();
        fixture.componentInstance.registerOnChange(onChange);
        fixture.componentInstance.modelChanged.subscribe(changed);

        openOverlay(fixture);
        overlayButton('gpt-b')!.click();
        fixture.detectChanges();

        expect(onChange).toHaveBeenCalledWith(31);
        expect(changed).toHaveBeenCalledWith({ model: GROUPS[2].models[1], provider: OPENAI });
        expect(trigger(fixture).textContent).toContain('OpenAI:');
        expect(trigger(fixture).textContent).toContain('gpt-b');
        expect(overlayButton('gpt-a')).toBeUndefined();
    });

    it('does not let a deprecated model be picked and flags it when it is the current value', () => {
        const { fixture } = render();

        openOverlay(fixture);
        expect(overlayButton('claude-old')!.disabled).toBe(true);

        fixture.componentInstance.writeValue(20);
        fixture.detectChanges();

        expect(trigger(fixture).textContent).toContain('Deprecated');
        expect((fixture.nativeElement as HTMLElement).textContent).toContain(
            'The model claude-old is deprecated and can no longer be used in new configurations.'
        );
    });

    it("opens the provider's model dialog from + Add model, and a custom model's from its edit button", () => {
        const { fixture, dialogOpen } = render();

        openOverlay(fixture);
        const addButtons = Array.from(document.querySelectorAll<HTMLElement>('app-button')).filter((button) =>
            button.textContent!.includes('+ Add model')
        );
        addButtons[0].querySelector('button')!.click();

        expect(dialogOpen).toHaveBeenCalledWith(CreateLlmModelModalComponent, {
            data: { provider: OPENAI },
            width: '600px',
        });

        const editButtons = document.querySelectorAll<HTMLElement>('app-icon-button button');
        expect(editButtons).toHaveLength(1);
        editButtons[0].click();

        expect(dialogOpen).toHaveBeenLastCalledWith(CreateLlmModelModalComponent, {
            data: { provider: OPENAI, model: GROUPS[2].models[1] },
            width: '600px',
        });
    });

    it('marks the form control touched when the list closes without a pick', () => {
        const { fixture } = render();
        const onTouched = vi.fn();
        fixture.componentInstance.registerOnTouched(onTouched);

        openOverlay(fixture);
        document.querySelector<HTMLElement>('.cdk-overlay-backdrop')!.click();
        fixture.detectChanges();

        expect(onTouched).toHaveBeenCalledOnce();
        expect(overlayButton('gpt-a')).toBeUndefined();
    });

    it('stops the trigger while the form disables it', () => {
        const { fixture } = render();

        fixture.componentInstance.setDisabledState(true);
        fixture.detectChanges();

        expect(trigger(fixture).disabled).toBe(true);
    });
});
