import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { TooltipComponent } from '@shared/components';
import { SystemOneConfig, SystemOneQuestion } from '@shared/models';
import { FullLLMConfigService, SystemOneConfigStorageService } from '@shared/services';
import { of } from 'rxjs';

import { PromptConfig } from '../../../../core/models/classification-decision-table.model';
import { NodePanelDiff } from '../../../../core/providers/node-panel-diff.token';
import { FieldChange, FieldName } from '../../../../utils/diff';
import {
    missingReference,
    provideChangesTabDiff,
    shownMissingReferenceNotes,
} from '../../../missing-reference-note/missing-reference-note.testing';
import { SHOWN_DIFF_MARKS } from '../../node-panel-diff.testing';
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

@Component({
    imports: [CdtSystemOneEntryComponent],
    template: `
        <app-cdt-system-one-entry [prompt]="prompt">
            <div promptName>Name field</div>
        </app-cdt-system-one-entry>
    `,
})
class HostWithNameComponent {
    readonly prompt = entry();
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

    it('labels the input map as the input to classify', () => {
        mount();

        const labels = [...host().querySelectorAll('.section__label')].map((label) => label.textContent?.trim());

        expect(labels).toContain('Input to classify');
        expect(labels).not.toContain('Input to the model');
    });

    it('shows the config select as a filled field, not a transparent one', () => {
        mount();

        expect(field('.config-select .selector__btn').classList).not.toContain('selector__btn--transparent');
    });

    it('lays a projected name field out in the same row as the config select', () => {
        TestBed.configureTestingModule({
            imports: [HostWithNameComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                {
                    provide: SystemOneConfigStorageService,
                    useValue: { configs: signal([TYPESAFE_CONFIG]), getAllConfigs: () => of([TYPESAFE_CONFIG]) },
                },
                { provide: FullLLMConfigService, useValue: { fullLLMConfigs: signal([]) } },
            ],
        });
        const hostFixture = TestBed.createComponent(HostWithNameComponent);
        hostFixture.detectChanges();
        const row = (hostFixture.nativeElement as HTMLElement).querySelector('.config-row')!;

        expect(row.querySelector('[promptName]')).not.toBeNull();
        expect(row.querySelector('app-select.config-select')).not.toBeNull();
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

    it('explains the selected question type in the type help', () => {
        mount();
        addQuestion();
        const typeHelp = (): string =>
            fixture.debugElement
                .queryAll(By.directive(TooltipComponent))
                .map((tooltip) => tooltip.componentInstance as TooltipComponent)
                .find((tooltip) => tooltip.label() === 'Question type')!
                .tooltipText();

        expect(typeHelp()).toMatch(/^Noul:/);
        pickOption(field('.question__type .selector__btn'), 'Choice');
        expect(typeHelp()).toMatch(/^Choice:/);
        pickOption(field('.question__type .selector__btn'), 'Score');
        expect(typeHelp()).toMatch(/^Score:/);
    });

    it('labels the name and type fields and has one help tooltip', () => {
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
        typeInto(field('input[placeholder="all fields"]'), '.company_name');

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

describe('CdtSystemOneEntryComponent on the Changes tab of a version preview', () => {
    let fixture: ComponentFixture<CdtSystemOneEntryComponent>;

    /** A change of one field of the entry "company_check" (or of the entry `promptKey`), as the diff reports it. */
    const promptChange = (
        field: string,
        current: unknown,
        version: unknown,
        promptKey = 'company_check'
    ): FieldChange => ({
        path: `prompts[key=${promptKey}].${field}`,
        field: `prompts[].${field}` as FieldName,
        status: 'changed',
        current,
        version,
    });

    /** The version entry, read-only, on a node a restore changes by `diff`. */
    async function open(prompt: Entry, diff: Partial<NodePanelDiff>): Promise<HTMLElement> {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideChangesTabDiff(diff),
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
        fixture.componentRef.setInput('readOnly', true);
        fixture.detectChanges();
        // The fields take their values from `ngModel`, which writes them after the first check.
        await fixture.whenStable();
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    /** What a screen reader hears as the description of `element`: for a mark, the tooltip's text. */
    const descriptionOf = (element: Element | null): string =>
        document.getElementById(element?.getAttribute('aria-describedby') ?? '')?.textContent ?? '';
    const shownMarks = (root: HTMLElement): HTMLElement[] =>
        Array.from(root.querySelectorAll<HTMLElement>('.diff-field-mark--shown'));
    const questionNamed = (root: HTMLElement, name: string): HTMLElement =>
        Array.from(root.querySelectorAll<HTMLElement>('.question')).find(
            (question) => question.querySelector('.question__name')?.textContent?.trim() === name
        )!;

    const QUESTIONS: Record<'correct' | 'tone' | 'quality', SystemOneQuestion> = {
        correct: { type: 'noul', instructions: 'Is it correct?' },
        tone: { type: 'choice', instructions: 'Which tone?', criteria: { calm: 'Calm', angry: 'Angry' } },
        quality: { type: 'score', instructions: 'How good?', criteria: ['low', 'high'] },
    };
    const versionEntry = entry({ system_one_config: 7, questions: QUESTIONS, input_map: { text: 'variables.text' } });

    it.each([
        { canvas: 8, shown: 'cheap — LLM: gpt-4o' },
        { canvas: 5, shown: 'System One config #5' },
        { canvas: null, shown: 'empty' },
    ])(
        'marks a changed config with the canvas config by its name ($canvas → $shown), without a badge',
        async ({ canvas, shown }) => {
            const root = await open(versionEntry, { fields: [promptChange('system_one_config', canvas, 7)] });

            const [mark] = shownMarks(root);
            expect(mark.querySelector('app-select')).not.toBeNull();
            expect(descriptionOf(mark)).toBe(`Current canvas: ${shown}`);
            expect(mark.classList).toContain('diff-value-marked--no-badge');
        }
    );

    it('marks a changed result variable without a badge', async () => {
        const root = await open(versionEntry, {
            fields: [promptChange('result_variable', 'verdict', 'company_check')],
        });

        const [mark] = shownMarks(root);
        expect(mark.querySelector('app-custom-input')).not.toBeNull();
        expect(descriptionOf(mark)).toBe('Current canvas: verdict');
        expect(mark.classList).toContain('diff-value-marked--no-badge');
    });

    it('marks only the fields of its own entry', async () => {
        const root = await open(versionEntry, {
            fields: [
                promptChange('system_one_config', 8, 7, 'other_entry'),
                promptChange('result_variable', 'a', 'b', 'other_entry'),
            ],
        });

        expect(shownMarks(root)).toEqual([]);
    });

    it('marks the input rows a restore changes, adds and removes', async () => {
        const root = await open(entry({ input_map: { text: 'variables.text', lang: 'variables.lang' } }), {
            fields: [
                promptChange(
                    'input_map',
                    { text: 'variables.body', author: 'variables.author' },
                    { text: 'variables.text', lang: 'variables.lang' }
                ),
            ],
        });

        const changed = root.querySelector('.readonly-row.diff-field-mark--shown');
        expect(changed?.textContent).toContain('text');
        expect(descriptionOf(changed)).toContain('variables.body');
        expect(root.querySelector('.readonly-row--added')?.textContent).toContain('lang');
        expect(root.querySelector('.readonly-row--removed')?.textContent).toContain('author');
    });

    it('marks each question a restore changes, naming the changed parts in its tooltip, and leaves the others', async () => {
        const root = await open(versionEntry, {
            fields: [
                promptChange(
                    'questions',
                    {
                        ...QUESTIONS,
                        correct: { type: 'noul', instructions: 'Is it right?' },
                        tone: { type: 'choice', instructions: 'Which tone?', criteria: { calm: 'Calm' } },
                    },
                    QUESTIONS
                ),
            ],
        });

        expect(descriptionOf(questionNamed(root, 'correct'))).toBe(
            'Restore changes this question. Changed fields: Instructions.'
        );
        expect(descriptionOf(questionNamed(root, 'tone'))).toBe(
            'Restore changes this question. Changed fields: Options.'
        );
        expect(questionNamed(root, 'quality').classList).not.toContain('diff-field-mark--shown');
        const changed = questionNamed(root, 'correct');
        expect(changed.getAttribute('role')).toBe('group');
        expect(changed.getAttribute('aria-label')).toBe('Question correct');
        expect(changed.getAttribute('tabindex')).toBe('0');
    });

    it('names a question whose type changed by its type and its new criteria', async () => {
        const root = await open(versionEntry, {
            fields: [
                promptChange(
                    'questions',
                    { ...QUESTIONS, quality: { type: 'choice', instructions: 'How good?', criteria: { ok: 'OK' } } },
                    QUESTIONS
                ),
            ],
        });

        expect(descriptionOf(questionNamed(root, 'quality'))).toBe(
            'Restore changes this question. Changed fields: Type, Levels.'
        );
    });

    it('shows a question a restore adds framed, and one it removes struck after the others', async () => {
        const canvasQuestions = { correct: QUESTIONS.correct, tone: QUESTIONS.tone };
        const root = await open(versionEntry, {
            fields: [
                promptChange(
                    'questions',
                    { ...canvasQuestions, legacy: { type: 'score', instructions: 'Old scale', criteria: ['a'] } },
                    QUESTIONS
                ),
            ],
        });

        const added = questionNamed(root, 'quality');
        expect(added.classList).toContain('question--added');
        expect(added.textContent).toContain('Restore adds this question');
        const removed = root.querySelector<HTMLElement>('.question--removed');
        expect(removed?.textContent).toContain('Restore removes this question');
        expect(removed?.textContent).toContain('legacy');
        expect(removed?.textContent).toContain('Score');
        expect(removed?.textContent).toContain('Old scale');
    });

    it('says under the config that the config of this entry no longer exists, and not for another entry', async () => {
        const root = await open(entry({ system_one_config: null }), {
            missingReferences: [
                missingReference('prompts[].system_one_config', 9, 'prompts[key=company_check].system_one_config'),
                missingReference('prompts[].system_one_config', 10, 'prompts[key=other_entry].system_one_config'),
            ],
        });

        expect(shownMissingReferenceNotes(root).map(({ text }) => text)).toEqual([
            'This version uses System One config #9; it no longer exists.',
        ]);
    });

    it.each([
        { case: 'the node is added', diff: { status: 'added' as const } },
        { case: 'the node is unchanged', diff: { status: 'unchanged' as const } },
    ])('shows no marks when $case', async ({ diff }) => {
        const root = await open(versionEntry, {
            ...diff,
            fields: [
                promptChange('system_one_config', 8, 7),
                promptChange('questions', { ...QUESTIONS, extra: QUESTIONS.correct }, QUESTIONS),
            ],
        });

        expect(root.querySelectorAll(SHOWN_DIFF_MARKS)).toHaveLength(0);
    });
});
