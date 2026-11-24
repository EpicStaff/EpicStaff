import { CUSTOM_ELEMENTS_SCHEMA, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule } from '@angular/forms';
import { By } from '@angular/platform-browser';
import { JsonSchema, SchemaFieldError, Secret } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';
import { of } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { JsonEditorComponent } from '../json-editor/json-editor.component';
import { SchemaFormComponent } from './schema-form.component';

/** The shape the backend's schema factory sends for an OpenAI chat model's settings. */
const PARAMETERS: JsonSchema = {
    type: 'object',
    additionalProperties: false,
    properties: {
        temperature: {
            type: 'number',
            title: 'Temperature',
            description: 'Controls randomness of responses.',
            default: 0.7,
            minimum: 0,
            maximum: 2,
            'x-step': 0.01,
            'x-widget': 'slider',
            'x-group': 'sampling',
        },
        top_p: {
            type: 'number',
            title: 'Top P',
            default: 1,
            minimum: 0.01,
            maximum: 1,
            'x-step': 0.01,
            'x-scale': 100,
            'x-widget': 'percent',
            'x-group': 'sampling',
        },
        max_tokens: {
            type: 'integer',
            title: 'Max tokens',
            default: 4096,
            minimum: 500,
            maximum: 16384,
            'x-step': 100,
            'x-widget': 'stepper',
            'x-group': 'output',
        },
        stop: {
            type: ['array', 'null'],
            title: 'Stop sequences',
            default: null,
            items: { type: 'string' },
            'x-widget': 'chips',
            'x-group': 'output',
        },
        logprobs: {
            type: 'boolean',
            title: 'Log probabilities',
            default: false,
            'x-widget': 'toggle',
            'x-group': 'output',
        },
        reasoning_effort: {
            type: ['string', 'null'],
            title: 'Reasoning effort',
            default: null,
            enum: ['low', 'high', null],
            'x-widget': 'select',
            'x-group': 'reasoning',
        },
        logit_bias: {
            type: ['object', 'null'],
            title: 'Logit bias',
            default: null,
            'x-widget': 'json',
            'x-group': 'advanced',
        },
    },
};

/** Every setting at its default, as the backend's `defaults` lists them. */
const DEFAULTS = { temperature: 0.7, top_p: 1, max_tokens: 4096, logprobs: false };

/** The shape the backend sends for a Bedrock-like provider's connection: no groups, no defaults. */
const CONNECTION: JsonSchema = {
    type: 'object',
    additionalProperties: false,
    required: ['base_url'],
    properties: {
        base_url: { type: 'string', title: 'Base URL', minLength: 1, 'x-widget': 'text' },
        aws_access_key_id: {
            type: 'string',
            title: 'AWS access key ID',
            pattern: '^epicstaff_secret\\(\\s*[^)]+?\\s*\\)$',
            'x-widget': 'secret',
        },
    },
};

const PROD_KEY = { id: 3, name: 'prod-key', tail: 'abcd' } as Secret;

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('SchemaFormComponent', () => {
    let fixture: ComponentFixture<SchemaFormComponent>;
    let element: HTMLElement;
    let emitted: Record<string, unknown>[];

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({
            providers: [
                { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
                {
                    provide: SecretsStorageService,
                    useValue: {
                        secrets: signal([PROD_KEY]),
                        secretsLoaded: signal(true),
                        getSecrets: () => of([PROD_KEY]),
                        maskTail: (tail: string) => `••••${tail}`,
                    },
                },
            ],
        });
        // Monaco does not run in jsdom: render its host element as an unknown custom element instead.
        TestBed.overrideComponent(JsonEditorComponent, {
            remove: { imports: [MonacoEditorModule, FormsModule] },
            add: { schemas: [CUSTOM_ELEMENTS_SCHEMA] },
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    function render(
        schema: JsonSchema,
        value: Record<string, unknown>,
        inputs: { path?: string; errors?: SchemaFieldError[] } = {}
    ): void {
        fixture = TestBed.createComponent(SchemaFormComponent);
        element = fixture.nativeElement as HTMLElement;
        emitted = [];
        fixture.componentInstance.valueChange.subscribe((next) => emitted.push(next));
        fixture.componentRef.setInput('schema', schema);
        fixture.componentRef.setInput('value', value);
        fixture.componentRef.setInput('path', inputs.path ?? '');
        fixture.componentRef.setInput('errors', inputs.errors ?? []);
        fixture.detectChanges();
    }

    function field(name: string): HTMLElement {
        return element.querySelector<HTMLElement>(`[data-field="${name}"]`)!;
    }

    function lastEmitted(): Record<string, unknown> | undefined {
        return emitted.at(-1);
    }

    /** Types into a text box and leaves it, as a user does. */
    function typeInto(input: HTMLInputElement, text: string, events: string[]): void {
        input.value = text;
        for (const event of events) input.dispatchEvent(new Event(event));
        fixture.detectChanges();
    }

    function sliderInput(name: string): HTMLInputElement {
        return field(name).querySelector<HTMLInputElement>('.slider-stepper__value-input')!;
    }

    function stepperInput(name: string): HTMLInputElement {
        return field(name).querySelector<HTMLInputElement>('.number-stepper__input')!;
    }

    function openSelect(name: string): string[] {
        field(name).querySelector<HTMLButtonElement>('.selector__btn')!.click();
        fixture.detectChanges();
        return Array.from(document.querySelectorAll('.selector__option .selector__text')).map(
            (option) => option.textContent?.trim() ?? ''
        );
    }

    function pickOption(text: string): void {
        const option = Array.from(document.querySelectorAll<HTMLElement>('.selector__option')).find(
            (candidate) => candidate.querySelector('.selector__text')?.textContent?.trim() === text
        )!;
        option.click();
        fixture.detectChanges();
    }

    function resetButton(name: string): HTMLButtonElement | null {
        return field(name).querySelector<HTMLButtonElement>('app-activate-button button');
    }

    it('shows the settings under their groups, in the order the schema lists them', () => {
        render(PARAMETERS, DEFAULTS);

        const headings = Array.from(element.querySelectorAll('.schema-form__group-title')).map((heading) =>
            heading.textContent?.trim()
        );
        expect(headings).toEqual(['Sampling', 'Output', 'Reasoning', 'Advanced']);
    });

    it('shows a setting missing from the value as not set, never at its default', () => {
        render(PARAMETERS, { temperature: 0.2 });

        expect(sliderInput('temperature').value).toBe('0.20');
        expect(stepperInput('max_tokens').value).toBe('');
        expect(emitted).toEqual([]);
    });

    it('keeps a setting with a default empty when the parent writes the emitted value back', () => {
        const schema: JsonSchema = {
            type: 'object',
            properties: { seed: { type: ['integer', 'null'], title: 'Seed', default: 7, 'x-widget': 'stepper' } },
        };
        render(schema, { seed: 7 });

        typeInto(stepperInput('seed'), '', ['input', 'blur']);
        expect(lastEmitted()).toEqual({});
        fixture.componentRef.setInput('value', lastEmitted());
        fixture.detectChanges();

        expect(stepperInput('seed').value).toBe('');
        expect(resetButton('seed')).not.toBeNull();
    });

    describe('slider', () => {
        it('sends a typed value', () => {
            render(PARAMETERS, DEFAULTS);

            typeInto(sliderInput('temperature'), '1.2', ['blur']);

            expect(lastEmitted()).toEqual({ ...DEFAULTS, temperature: 1.2 });
        });

        it.each([
            ['above the maximum', '3', 2],
            ['below the minimum', '-1', 0],
        ])('keeps a value typed %s at the limit', (_case, typed, sent) => {
            render(PARAMETERS, DEFAULTS);

            typeInto(sliderInput('temperature'), typed, ['blur']);

            expect(lastEmitted()?.['temperature']).toBe(sent);
        });
    });

    describe('percent', () => {
        it('shows 0.7 as 70 %', () => {
            render(PARAMETERS, { ...DEFAULTS, top_p: 0.7 });

            expect(sliderInput('top_p').value).toBe('70');
            expect(field('top_p').querySelector('.slider-stepper__suffix')?.textContent?.trim()).toBe('%');
        });

        it.each([
            ['a percent within the range', '50', 0.5],
            ['a percent above 100', '150', 1],
            ['a percent below the minimum', '0', 0.01],
        ])('sends %s as a fraction', (_case, typed, sent) => {
            render(PARAMETERS, DEFAULTS);

            typeInto(sliderInput('top_p'), typed, ['blur']);

            expect(lastEmitted()?.['top_p']).toBe(sent);
        });
    });

    describe('stepper', () => {
        it('sends a typed whole number', () => {
            render(PARAMETERS, DEFAULTS);

            typeInto(stepperInput('max_tokens'), '8000', ['input', 'blur']);

            expect(lastEmitted()?.['max_tokens']).toBe(8000);
        });

        it.each([
            ['above the model maximum', '99999', 16384],
            ['below the minimum', '100', 500],
        ])('keeps a number typed %s at the limit', (_case, typed, sent) => {
            render(PARAMETERS, DEFAULTS);

            typeInto(stepperInput('max_tokens'), typed, ['input', 'blur']);

            expect(lastEmitted()?.['max_tokens']).toBe(sent);
        });
    });

    it('toggle: switching it on sends true', () => {
        render(PARAMETERS, DEFAULTS);

        field('logprobs').querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
        fixture.detectChanges();

        expect(lastEmitted()?.['logprobs']).toBe(true);
    });

    describe('select', () => {
        it('offers only the levels the model accepts, and "Not set" when the setting may be unset', () => {
            render(PARAMETERS, DEFAULTS);

            expect(openSelect('reasoning_effort')).toEqual(['Not set', 'low', 'high']);
        });

        it('sends the picked level, and leaves the setting out once it is "Not set" again', () => {
            render(PARAMETERS, DEFAULTS);

            openSelect('reasoning_effort');
            pickOption('high');
            expect(lastEmitted()?.['reasoning_effort']).toBe('high');

            openSelect('reasoning_effort');
            pickOption('Not set');
            expect(lastEmitted()).toEqual(DEFAULTS);
        });
    });

    it('chips: sends each added stop sequence, and leaves an empty list out', () => {
        render(PARAMETERS, { ...DEFAULTS, stop: ['END'] });
        const chipInput = field('stop').querySelector<HTMLInputElement>('app-chips-input input')!;

        typeInto(chipInput, '###', ['input']);
        chipInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        fixture.detectChanges();
        expect(lastEmitted()?.['stop']).toEqual(['END', '###']);

        for (let removed = 0; removed < 2; removed++) {
            field('stop').querySelector<HTMLButtonElement>('.chip button')!.click();
            fixture.detectChanges();
        }
        expect(lastEmitted()).not.toHaveProperty('stop');
    });

    it('json: sends the typed mapping as an object', () => {
        render(PARAMETERS, DEFAULTS);
        const editor = fixture.debugElement
            .query(By.css('[data-field="logit_bias"]'))
            .query(By.directive(JsonEditorComponent)).componentInstance as JsonEditorComponent;

        editor.jsonChange.emit('{"50256": -100}');
        fixture.detectChanges();

        expect(lastEmitted()?.['logit_bias']).toEqual({ '50256': -100 });
    });

    describe('text', () => {
        it('sends a typed connection field and marks a required one', () => {
            render(CONNECTION, {}, { path: 'connection' });

            typeInto(field('base_url').querySelector<HTMLInputElement>('input')!, 'https://proxy.example.com', [
                'input',
            ]);

            expect(lastEmitted()).toEqual({ base_url: 'https://proxy.example.com' });
            expect(field('base_url').querySelector('.required')).not.toBeNull();
        });

        it('leaves an emptied field out instead of sending an empty text', () => {
            render(CONNECTION, { base_url: 'https://proxy.example.com' }, { path: 'connection' });

            typeInto(field('base_url').querySelector<HTMLInputElement>('input')!, '', ['input']);

            expect(lastEmitted()).toEqual({});
        });
    });

    describe('secret', () => {
        it('offers the organization secrets by name and stores the picked one as a marker', () => {
            render(CONNECTION, { base_url: 'https://proxy.example.com' }, { path: 'connection' });

            expect(openSelect('aws_access_key_id')).toEqual(['Not set', 'prod-key']);
            pickOption('prod-key');

            expect(lastEmitted()).toEqual({
                base_url: 'https://proxy.example.com',
                aws_access_key_id: 'epicstaff_secret(prod-key)',
            });
        });

        it('names a stored secret that is no longer among the secrets as missing', () => {
            render(CONNECTION, { aws_access_key_id: 'epicstaff_secret(old-key)' }, { path: 'connection' });

            expect(field('aws_access_key_id').querySelector('.selector__btn')?.textContent).toContain(
                'old-key (missing)'
            );
            expect(openSelect('aws_access_key_id')).toEqual(['Not set', 'prod-key', 'old-key (missing)']);
        });

        it('clears an optional secret with "Not set"', () => {
            render(CONNECTION, { aws_access_key_id: 'epicstaff_secret(prod-key)' }, { path: 'connection' });

            openSelect('aws_access_key_id');
            pickOption('Not set');

            expect(lastEmitted()).toEqual({});
        });

        it('offers no "Not set" for a required secret', () => {
            render({ ...CONNECTION, required: ['aws_access_key_id'] }, {}, { path: 'connection' });

            expect(openSelect('aws_access_key_id')).toEqual(['prod-key']);
        });
    });

    describe('reset', () => {
        it('offers ↺ only on a changed setting, and ↺ puts it back to its default', () => {
            render(PARAMETERS, DEFAULTS);
            expect(resetButton('temperature')).toBeNull();

            typeInto(sliderInput('temperature'), '1.2', ['blur']);
            const reset = resetButton('temperature')!;
            expect(reset.getAttribute('aria-label')).toBe('Reset Temperature to default');
            reset.click();
            fixture.detectChanges();

            expect(lastEmitted()).toEqual(DEFAULTS);
            expect(sliderInput('temperature').value).toBe('0.70');
            expect(resetButton('temperature')).toBeNull();
        });

        it('offers no ↺ on a connection field, which has no default', () => {
            render(CONNECTION, { base_url: 'https://proxy.example.com' }, { path: 'connection' });

            expect(resetButton('base_url')).toBeNull();
        });

        it('resetAll puts every setting back to its default and unsets the rest', () => {
            render(PARAMETERS, { temperature: 1.5, top_p: 0.5, max_tokens: 1000, stop: ['END'], logprobs: true });

            fixture.componentInstance.resetAll();
            fixture.detectChanges();

            expect(lastEmitted()).toEqual(DEFAULTS);
        });
    });

    it('shows a server error for parameters.temperature under that field only', () => {
        render(
            PARAMETERS,
            { ...DEFAULTS, temperature: 1.5 },
            {
                path: 'parameters',
                errors: [
                    { field: 'parameters.temperature', reason: 'Must be at most 1.' },
                    { field: 'connection.base_url', reason: 'This field is required.' },
                ],
            }
        );

        expect(field('temperature').querySelector('[role="alert"]')?.textContent?.trim()).toBe('Must be at most 1.');
        expect(element.querySelectorAll('[role="alert"]')).toHaveLength(1);
    });
});
