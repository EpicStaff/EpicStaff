import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { SystemOneConfig } from '@shared/models';
import { FullLLMConfigService, SystemOneConfigStorageService } from '@shared/services';
import { of } from 'rxjs';

import { PromptConfig } from '../../../../core/models/classification-decision-table.model';
import { CdtSystemOneEntryComponent } from './cdt-system-one-entry.component';

const TYPESAFE_CONFIG = { id: 7, custom_name: 'jev', provider: 'typesafe', model_name: 'Jev 1.14' } as SystemOneConfig;
const LLM_CONFIG = { id: 8, custom_name: 'cheap', provider: 'llm', llm_config: 4 } as SystemOneConfig;

type Entry = PromptConfig & { id: string };

function entry(overrides: Partial<PromptConfig> = {}): Entry {
    return {
        id: 'company_check',
        prompt_text: '',
        llm_config: null,
        output_schema: null,
        result_variable: 'company_check',
        variable_mappings: {},
        kind: 'system_one',
        system_one_config: null,
        questions: {},
        input_map: {},
        ...overrides,
    };
}

describe('CdtSystemOneEntryComponent', () => {
    let fixture: ComponentFixture<CdtSystemOneEntryComponent>;
    let changes: Partial<PromptConfig>[];

    function mount(prompt: Entry = entry(), readOnly = false): void {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                {
                    provide: SystemOneConfigStorageService,
                    useValue: {
                        configs: signal([TYPESAFE_CONFIG, LLM_CONFIG]),
                        getAllConfigs: () => of([TYPESAFE_CONFIG, LLM_CONFIG]),
                    },
                },
                {
                    provide: FullLLMConfigService,
                    useValue: { fullLLMConfigs: signal([{ id: 4, custom_name: 'gpt-4o' }]) },
                },
            ],
        });
        fixture = TestBed.createComponent(CdtSystemOneEntryComponent);
        fixture.componentRef.setInput('prompt', prompt);
        fixture.componentRef.setInput('readOnly', readOnly);
        changes = [];
        fixture.componentInstance.promptChange.subscribe((change) => changes.push(change));
        fixture.detectChanges();
    }

    const host = (): HTMLElement => fixture.nativeElement as HTMLElement;

    function field<T extends HTMLElement>(selector: string): T {
        const found = host().querySelector<T>(selector);
        if (!found) throw new Error(`nothing matches ${selector}`);
        return found;
    }

    function typeInto(element: HTMLInputElement | HTMLTextAreaElement, value: string): void {
        element.value = value;
        element.dispatchEvent(new Event('input', { bubbles: true }));
        fixture.detectChanges();
    }

    function pressEnter(element: HTMLElement): void {
        element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        fixture.detectChanges();
    }

    function pickOption(trigger: HTMLElement, optionName: string): void {
        trigger.click();
        fixture.detectChanges();
        const option = [...document.querySelectorAll<HTMLElement>('.selector__option')].find(
            (candidate) => candidate.textContent?.trim() === optionName
        );
        if (!option) throw new Error(`no option ${optionName}`);
        option.click();
        fixture.detectChanges();
    }

    function addQuestion(): void {
        const button = [...host().querySelectorAll('button')].find((candidate) =>
            candidate.textContent?.includes('Add question')
        );
        button!.click();
        fixture.detectChanges();
    }

    function lastQuestions(): unknown {
        return [...changes].reverse().find((change) => change.questions)?.questions;
    }

    afterEach(() => {
        document.querySelectorAll('.cdk-overlay-container').forEach((element) => (element.innerHTML = ''));
    });

    beforeAll(() => {
        const scope = globalThis as unknown as { ResizeObserver?: unknown };
        scope.ResizeObserver ??= class {
            observe(): void {}
            unobserve(): void {}
            disconnect(): void {}
        };
    });

    it('emits the chosen config', () => {
        mount();

        pickOption(field('.config-select .selector__btn'), 'jev — Jev 1.14 (TypeSafe)');

        expect(changes).toEqual([{ system_one_config: 7 }]);
    });

    it('labels an LLM-backed config with the LLM it uses', () => {
        mount();

        field<HTMLElement>('.config-select .selector__btn').click();
        fixture.detectChanges();
        const names = [...document.querySelectorAll('.selector__option .selector__text')].map((option) =>
            option.textContent?.trim()
        );

        expect(names).toEqual(['jev — Jev 1.14 (TypeSafe)', 'cheap — LLM: gpt-4o']);
    });

    it('emits the result variable as it is typed', () => {
        mount();

        typeInto(field('input[placeholder="e.g. classification"]'), 'verdict');

        expect(changes).toEqual([{ result_variable: 'verdict' }]);
    });

    it('labels the name and type fields and explains all three types in one help text', () => {
        mount();

        addQuestion();

        const labels = [...host().querySelectorAll('.question__header .tooltip-label-text')].map((label) =>
            label.textContent?.trim()
        );
        expect(labels).toEqual(['Question name', 'Question type']);
        expect(host().querySelectorAll('.question__header app-help-tooltip')).toHaveLength(1);
        expect(field('input[aria-label="Question name"]').getAttribute('placeholder')).toBe('e.g. correctness');
    });

    it('emits a new Noul question once it has a name and instructions', () => {
        mount();

        addQuestion();
        typeInto(field('input[aria-label="Question name"]'), 'is_engineering');
        expect(lastQuestions()).toEqual({});
        typeInto(field('textarea'), 'Does the company build engineering products?');

        expect(lastQuestions()).toEqual({
            is_engineering: { type: 'noul', instructions: 'Does the company build engineering products?' },
        });
    });

    it('shows the name error and holds back a question named like a Python keyword', () => {
        mount();

        addQuestion();
        typeInto(field('input[aria-label="Question name"]'), 'class');
        typeInto(field('textarea'), 'Anything');

        expect(host().textContent).toContain("Use letters, digits and _; don't start with _ or use a Python keyword.");
        expect(lastQuestions()).toEqual({});
    });

    it('holds back the second of two questions with the same name', () => {
        mount();

        for (const instructions of ['First?', 'Second?']) {
            addQuestion();
            const names = host().querySelectorAll<HTMLInputElement>('input[aria-label="Question name"]');
            const areas = host().querySelectorAll<HTMLTextAreaElement>('textarea');
            typeInto(names[names.length - 1], 'dup');
            typeInto(areas[areas.length - 1], instructions);
        }

        expect(lastQuestions()).toEqual({ dup: { type: 'noul', instructions: 'First?' } });
        expect(host().textContent).toContain('already used');
    });

    it('emits the meaning of true and false on a Noul question, and drops one that was cleared', () => {
        mount();
        addQuestion();
        typeInto(field('input[aria-label="Question name"]'), 'q');
        typeInto(field('textarea'), 'Is it?');

        typeInto(field('input[aria-label="True means"]'), 'yes');
        typeInto(field('input[aria-label="False means"]'), 'no');
        expect(lastQuestions()).toEqual({
            q: { type: 'noul', instructions: 'Is it?', criteria: { true: 'yes', false: 'no' } },
        });

        typeInto(field('input[aria-label="True means"]'), '');
        typeInto(field('input[aria-label="False means"]'), '');
        expect(lastQuestions()).toEqual({ q: { type: 'noul', instructions: 'Is it?' } });
    });

    it('emits a Choice question once it has an option', async () => {
        mount();
        addQuestion();
        typeInto(field('input[aria-label="Question name"]'), 'department');
        typeInto(field('textarea'), 'Which department?');

        pickOption(field('.question__type .selector__btn'), 'Choice');
        await fixture.whenStable();
        expect(lastQuestions()).toEqual({ department: { type: 'noul', instructions: 'Which department?' } });

        typeInto(field('input[aria-label="Option name, row 1"]'), 'eng');
        typeInto(field('input[aria-label="Option value, row 1"]'), 'Engineering');

        expect(lastQuestions()).toEqual({
            department: { type: 'choice', instructions: 'Which department?', criteria: { eng: 'Engineering' } },
        });
    });

    it('emits Score levels in the order they were added', () => {
        mount();
        addQuestion();
        typeInto(field('input[aria-label="Question name"]'), 'seniority');
        typeInto(field('textarea'), 'How senior?');
        pickOption(field('.question__type .selector__btn'), 'Score');

        for (const level of ['junior', 'mid', 'senior']) {
            const levelInput = field<HTMLInputElement>('input[placeholder="Add a level…"]');
            typeInto(levelInput, level);
            pressEnter(levelInput);
        }

        expect(lastQuestions()).toEqual({
            seniority: { type: 'score', instructions: 'How senior?', criteria: ['junior', 'mid', 'senior'] },
        });
    });

    it('starts the criteria over when the type changes, and keeps the saved version until the new one is complete', () => {
        const saved = { type: 'choice', instructions: 'Which?', criteria: { a: 'A' } } as const;
        mount(entry({ questions: { q: saved } }));

        pickOption(field('.question__type .selector__btn'), 'Score');

        expect(lastQuestions()).toEqual({ q: saved });
        expect(host().textContent).toContain('the last saved version is kept');
    });

    it('keeps a saved question in the sent map while its instructions are blanked, and sends the edit once valid', () => {
        const saved = { type: 'noul', instructions: 'Is it?' } as const;
        mount(entry({ questions: { q: saved } }));

        typeInto(field('textarea'), '');
        expect(lastQuestions()).toEqual({ q: saved });

        typeInto(field('textarea'), 'Is it really?');
        expect(lastQuestions()).toEqual({ q: { type: 'noul', instructions: 'Is it really?' } });
    });

    it('keeps the saved name while the question is renamed to something invalid or taken', () => {
        const first = { type: 'noul', instructions: 'First?' } as const;
        const second = { type: 'noul', instructions: 'Second?' } as const;
        mount(entry({ questions: { a: first, b: second } }));
        const names = (): HTMLInputElement[] => [
            ...host().querySelectorAll<HTMLInputElement>('input[aria-label="Question name"]'),
        ];

        typeInto(names()[1], 'class');
        expect(lastQuestions()).toEqual({ a: first, b: second });

        typeInto(names()[1], 'a');
        expect(lastQuestions()).toEqual({ a: first, b: second });
    });

    it('does not say the last saved version is kept for a row whose saved name another row now sends', () => {
        const first = { type: 'noul', instructions: 'First?' } as const;
        const second = { type: 'noul', instructions: 'Second?' } as const;
        mount(entry({ questions: { a: first, b: second } }));

        typeInto(field<HTMLInputElement>('input[aria-label="Question name"]'), 'b');

        const secondRow = host().querySelectorAll<HTMLElement>('.question')[1];
        expect(lastQuestions()).toEqual({ b: first });
        expect(secondRow.textContent).toContain('already used');
        expect(secondRow.textContent).not.toContain('the last saved version is kept');
    });

    it('removes a question the user deletes', () => {
        mount(entry({ questions: { q: { type: 'noul', instructions: 'Is it?' } } }));

        field<HTMLElement>('app-delete-button button').click();
        fixture.detectChanges();

        expect(lastQuestions()).toEqual({});
        expect(host().querySelector('input[aria-label="Question name"]')).toBeNull();
    });

    it('sends a loaded question back in the order it came, once an edit is reverted', () => {
        const loaded = { type: 'noul', criteria: { true: 'yes' }, instructions: 'Eng?' } as const;
        mount(entry({ questions: { q: loaded } }));

        typeInto(field('input[aria-label="True means"]'), 'yes!');
        typeInto(field('input[aria-label="True means"]'), 'yes');

        expect(JSON.stringify(lastQuestions())).toBe(JSON.stringify({ q: loaded }));
    });

    it('emits the input map as a record, without rows that have no name', () => {
        mount();

        typeInto(field('input[placeholder="Name"]'), 'company');
        typeInto(field('input[placeholder="Domain Variable Name"]'), 'variables.company_name');

        expect(changes[changes.length - 1]).toEqual({ input_map: { company: 'variables.company_name' } });
    });

    it('shows the stored input map and emits nothing before the user edits', () => {
        mount(entry({ input_map: { company: 'variables.company_name' } }));

        expect(field<HTMLInputElement>('input[placeholder="Name"]').value).toBe('company');
        expect(changes).toEqual([]);
    });

    it.each([
        [7, false],
        [8, true],
        [null, false],
    ])('shows the LLM warning only for an LLM-backed config (config %s -> %s)', (config, warns) => {
        mount(entry({ system_one_config: config }));

        expect(host().textContent?.includes('This config uses an LLM.')).toBe(warns);
    });

    it('names the entry and its first question in the routing hint', () => {
        mount(
            entry({ result_variable: 'verdict', questions: { is_engineering: { type: 'noul', instructions: 'x' } } })
        );

        expect(host().textContent).toContain('verdict.answers.is_engineering.noul > 0.8');
    });

    it('falls back to <question> in the routing hint while there are no questions', () => {
        mount();

        expect(host().textContent).toContain('company_check.answers.<question>.noul > 0.8');
    });

    it('disables the add button when read-only', () => {
        mount(entry(), true);

        const button = [...host().querySelectorAll('button')].find((candidate) =>
            candidate.textContent?.includes('Add question')
        );

        expect(button!.disabled).toBe(true);
    });
});
