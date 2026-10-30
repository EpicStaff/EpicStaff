import { Component, computed, DestroyRef, inject, input, OnInit, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormControl, FormGroup, FormsModule, ReactiveFormsModule } from '@angular/forms';
import {
    ButtonComponent,
    ChipsInputComponent,
    CustomInputComponent,
    DeleteButtonComponent,
    HelpTooltipComponent,
    HintMessageComponent,
    KeyValueListComponent,
    SelectComponent,
    SelectItem,
    TextareaComponent,
} from '@shared/components';
import { SystemOneConfig, SystemOneQuestion } from '@shared/models';
import { FullLLMConfigService, SystemOneConfigStorageService } from '@shared/services';
import { deepEqual } from '@shared/utils';

import { PromptConfig } from '../../../../core/models/classification-decision-table.model';
import { InputMapComponent } from '../../../input-map/input-map.component';
import { isCompleteQuestion, isValidQuestionName } from './question-name.util';

type QuestionType = SystemOneQuestion['type'];

interface QuestionRow {
    uid: number;
    name: string;
    question: SystemOneQuestion;
    /** The question as it was loaded, sent back unchanged once edits return to it, so reverting leaves the node clean. */
    original: SystemOneQuestion | null;
    /** The last version of this row that was valid. An invalid edit sends it instead, so a saved question is never deleted mid-edit. */
    lastValid: { name: string; question: SystemOneQuestion } | null;
}

interface QuestionView {
    nameError: string | null;
    note: string | null;
    sent: boolean;
}

interface QuestionViewRow {
    row: QuestionRow;
    view: QuestionView;
}

const NAME_ERROR = "Use letters, digits and _; don't start with _ or use a Python keyword.";
const DUPLICATE_NAME_ERROR = 'This name is already used by another question.';
const NOT_SAVED_NOTE = 'Not saved yet: add a name, instructions and any options or levels it needs.';
const KEPT_VERSION_NOTE = 'Not saved yet; the last saved version is kept.';

const QUESTION_TYPE_ITEMS: SelectItem<QuestionType>[] = [
    { name: 'Noul', value: 'noul' },
    { name: 'Choice', value: 'choice' },
    { name: 'Score', value: 'score' },
];

@Component({
    selector: 'app-cdt-system-one-entry',
    imports: [
        FormsModule,
        ReactiveFormsModule,
        ButtonComponent,
        ChipsInputComponent,
        CustomInputComponent,
        DeleteButtonComponent,
        HelpTooltipComponent,
        HintMessageComponent,
        InputMapComponent,
        KeyValueListComponent,
        SelectComponent,
        TextareaComponent,
    ],
    templateUrl: './cdt-system-one-entry.component.html',
    styleUrl: './cdt-system-one-entry.component.scss',
})
export class CdtSystemOneEntryComponent implements OnInit {
    readonly prompt = input.required<PromptConfig & { id: string }>();
    readonly readOnly = input(false);
    readonly promptChange = output<Partial<PromptConfig>>();

    protected readonly typeItems = QUESTION_TYPE_ITEMS;
    protected readonly inputMapForm = new FormGroup({
        input_map: new FormArray<FormGroup>([]),
        test_input: new FormArray<FormGroup>([]),
    });

    private readonly rows = signal<QuestionRow[]>([]);
    private readonly destroyRef = inject(DestroyRef);
    private readonly configStorage = inject(SystemOneConfigStorageService);
    private readonly llmConfigs = inject(FullLLMConfigService);
    private nextRowUid = 0;

    protected readonly configItems = computed<SelectItem<number>[]>(() =>
        this.configStorage.configs().map((config) => ({ name: this.configLabel(config), value: config.id }))
    );

    protected readonly isLlmBacked = computed(
        () =>
            this.configStorage.configs().find((config) => config.id === this.prompt().system_one_config)?.provider ===
            'llm'
    );

    protected readonly questionViews = computed<QuestionViewRow[]>(() => this.viewRows(this.rows()));

    protected readonly hintExample = computed(() => {
        const first = this.questionViews().find(({ view }) => view.sent)?.row;
        return {
            resultVariable: this.prompt().result_variable || '<result_variable>',
            question: first?.name ?? '<question>',
            condition: first ? this.conditionFor(first.question) : 'noul > 0.8',
        };
    });

    ngOnInit(): void {
        this.configStorage.getAllConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();

        this.rows.set(
            Object.entries(this.prompt().questions ?? {}).map(([name, question]) =>
                this.createRow(name, question, question, { name, question })
            )
        );

        const pairs = this.inputMapForm.controls.input_map;
        for (const [key, value] of Object.entries(this.prompt().input_map ?? {})) {
            pairs.push(new FormGroup({ key: new FormControl(key), value: new FormControl(value) }), {
                emitEvent: false,
            });
        }
        pairs.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.emitInputMap());
    }

    protected onConfigChange(configId: unknown): void {
        this.promptChange.emit({ system_one_config: typeof configId === 'number' ? configId : null });
    }

    protected onResultVariableChange(resultVariable: string): void {
        this.promptChange.emit({ result_variable: resultVariable });
    }

    protected addQuestion(): void {
        this.commit([...this.rows(), this.createRow('', { type: 'noul', instructions: '' }, null, null)]);
    }

    protected removeQuestion(row: QuestionRow): void {
        this.commit(this.rows().filter((candidate) => candidate !== row));
    }

    protected onNameChange(row: QuestionRow, name: string): void {
        this.replaceRow(row, { ...row, name });
    }

    protected onTypeChange(row: QuestionRow, type: unknown): void {
        if (type === row.question.type) return;
        const instructions = row.question.instructions;
        const question: SystemOneQuestion =
            type === 'choice'
                ? { type, instructions, criteria: {} }
                : type === 'score'
                  ? { type, instructions, criteria: [] }
                  : { type: 'noul', instructions };
        this.replaceRow(row, { ...row, question });
    }

    protected onInstructionsChange(row: QuestionRow, instructions: string): void {
        this.replaceRow(row, { ...row, question: { ...row.question, instructions } });
    }

    protected noulMeaning(question: SystemOneQuestion, answer: 'true' | 'false'): string {
        return question.type === 'noul' ? (question.criteria?.[answer] ?? '') : '';
    }

    protected onNoulMeaningChange(row: QuestionRow, answer: 'true' | 'false', meaning: string): void {
        if (row.question.type !== 'noul') return;
        const meanings = { ...row.question.criteria, [answer]: meaning };
        const criteria = {
            ...(meanings.true?.trim() ? { true: meanings.true } : {}),
            ...(meanings.false?.trim() ? { false: meanings.false } : {}),
        };
        const question: SystemOneQuestion = {
            type: 'noul',
            instructions: row.question.instructions,
            ...(Object.keys(criteria).length > 0 ? { criteria } : {}),
        };
        this.replaceRow(row, { ...row, question });
    }

    protected choiceOptions(question: SystemOneQuestion): Record<string, string> {
        return question.type === 'choice' ? question.criteria : {};
    }

    protected onChoiceOptionsChange(row: QuestionRow, criteria: Record<string, string>): void {
        if (row.question.type !== 'choice') return;
        this.replaceRow(row, { ...row, question: { ...row.question, criteria } });
    }

    protected scoreLevels(question: SystemOneQuestion): string[] {
        return question.type === 'score' ? question.criteria : [];
    }

    protected onScoreLevelsChange(row: QuestionRow, criteria: string[]): void {
        if (row.question.type !== 'score') return;
        this.replaceRow(row, { ...row, question: { ...row.question, criteria } });
    }

    private createRow(
        name: string,
        question: SystemOneQuestion,
        original: SystemOneQuestion | null,
        lastValid: QuestionRow['lastValid']
    ): QuestionRow {
        return { uid: this.nextRowUid++, name, question, original, lastValid };
    }

    private viewRows(rows: QuestionRow[]): QuestionViewRow[] {
        const seenNames = new Set<string>();
        const duplicates = rows.map((row) => {
            const isDuplicate = seenNames.has(row.name);
            seenNames.add(row.name);
            return isDuplicate;
        });
        const sent = rows.map((row, index) => !duplicates[index] && isCompleteQuestion(row.name, row.question));
        const versions = this.versionsToSend(rows, sent);
        return rows.map((row, index) => {
            let nameError: string | null = null;
            if (row.name !== '') {
                if (!isValidQuestionName(row.name)) nameError = NAME_ERROR;
                else if (duplicates[index]) nameError = DUPLICATE_NAME_ERROR;
            }
            const note = sent[index] ? null : versions[index] ? KEPT_VERSION_NOTE : nameError ? null : NOT_SAVED_NOTE;
            return { row, view: { nameError, note, sent: sent[index] } };
        });
    }

    /** A sent row sends its current version. Any other row sends its last valid version, unless another row already sends that name. */
    private versionsToSend(rows: QuestionRow[], sent: boolean[]): QuestionRow['lastValid'][] {
        const takenNames = new Set(rows.filter((_, index) => sent[index]).map((row) => row.name));
        return rows.map((row, index) => {
            const version = row.lastValid;
            if (sent[index]) return version;
            if (!version || takenNames.has(version.name)) return null;
            takenNames.add(version.name);
            return version;
        });
    }

    private replaceRow(row: QuestionRow, replacement: QuestionRow): void {
        this.commit(this.rows().map((candidate) => (candidate === row ? replacement : candidate)));
    }

    private commit(rows: QuestionRow[]): void {
        const sent = this.viewRows(rows).map(({ view }) => view.sent);
        const kept = rows.map((row, index) =>
            sent[index]
                ? {
                      ...row,
                      lastValid: {
                          name: row.name,
                          question: row.original && deepEqual(row.question, row.original) ? row.original : row.question,
                      },
                  }
                : row
        );
        this.rows.set(kept);

        const questions: Record<string, SystemOneQuestion> = {};
        this.versionsToSend(kept, sent).forEach((version) => {
            if (version) questions[version.name] = version.question;
        });
        this.promptChange.emit({ questions });
    }

    private emitInputMap(): void {
        const pairs: { key: string | null; value: string | null }[] = this.inputMapForm.controls.input_map.value;
        const inputMap = Object.fromEntries(
            pairs.filter((pair) => pair.key?.trim()).map((pair) => [pair.key!.trim(), pair.value ?? ''])
        );
        if (deepEqual(inputMap, this.prompt().input_map ?? {})) return;
        this.promptChange.emit({ input_map: inputMap });
    }

    private configLabel(config: SystemOneConfig): string {
        if (config.provider === 'llm') {
            const llm = this.llmConfigs.fullLLMConfigs().find((candidate) => candidate.id === config.llm_config);
            const llmName = llm ? llm.custom_name || `LLM #${llm.id}` : '';
            return llmName ? `${config.custom_name} — LLM: ${llmName}` : `${config.custom_name} — LLM`;
        }
        return config.model_name
            ? `${config.custom_name} — ${config.model_name} (TypeSafe)`
            : `${config.custom_name} — TypeSafe`;
    }

    private conditionFor(question: SystemOneQuestion): string {
        if (question.type === 'choice') return `choice == "${Object.keys(question.criteria)[0] ?? '<option>'}"`;
        return question.type === 'score' ? 'score > 1' : 'noul > 0.8';
    }
}
