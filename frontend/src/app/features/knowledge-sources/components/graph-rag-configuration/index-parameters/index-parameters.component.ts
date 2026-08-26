import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    input,
    OnInit,
    output,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AbstractControl, FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    ChipsInputComponent,
    HelpTooltipComponent,
    InputNumberComponent,
    JsonEditorComponent,
    RadioButtonComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { ServerErrorsDirective, ServerErrorsRef } from '@shared/directives';
import { ApiErrorItem } from '@shared/models';

import { GraphRagFileType, GraphRagIndexConfig } from '../../../models/graph-rag.model';

const CONFIG_FIELDS = [
    'chunk_strategy',
    'chunk_size',
    'chunk_overlap',
    'entity_types',
    'max_gleanings',
    'max_cluster_size',
] as const;

@Component({
    selector: 'app-graph-rag-index-parameters',
    templateUrl: './index-parameters.component.html',
    styleUrls: ['./index-parameters.component.scss'],
    imports: [
        RadioButtonComponent,
        ChipsInputComponent,
        InputNumberComponent,
        HelpTooltipComponent,
        ReactiveFormsModule,
        ValidationErrorsComponent,
        JsonEditorComponent,
        ButtonComponent,
        ServerErrorsDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppGraphRagParametersComponent implements OnInit {
    private fb = inject(FormBuilder);
    private destroyRef = inject(DestroyRef);

    indexConfig = input<GraphRagIndexConfig | null>(null);
    selectedFormat = input<GraphRagFileType>('text');
    readonly = input<boolean>(false);

    reset = output<void>();

    readonly serverErrorsRef = new ServerErrorsRef();

    formValue = signal<Partial<GraphRagIndexConfig> | null>(null);
    private formSnapshot = signal<Partial<GraphRagIndexConfig> | null>(null);
    isJsonValid = signal(true);
    jsonData = computed(() => {
        return JSON.stringify(
            {
                file_type: this.selectedFormat(),
                ...this.formValue(),
            },
            null,
            2
        );
    });

    hasUnsavedFormChanges = computed(() => {
        const saved = this.indexConfig();
        const current = this.formSnapshot();
        if (!saved || !current) return false;
        return CONFIG_FIELDS.some((k) => JSON.stringify(saved[k]) !== JSON.stringify(current[k]));
    });

    form!: FormGroup;
    editorOptions: Record<string, unknown> = {
        lineNumbers: 'off',
        theme: 'vs-dark',
        language: 'json',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        wrappingIndent: 'indent',
        wordWrapBreakAfterCharacters: ',',
        wordWrapBreakBeforeCharacters: '}]',
        tabSize: 2,
    };
    private patchingFromJson = false;
    chunkStrategyOptions: SelectItem[] = [
        {
            name: 'tokens',
            value: 'tokens',
        },
        {
            name: 'sentences',
            value: 'sentence',
        },
    ];

    constructor() {
        effect(() => {
            if (!this.form) return;
            if (this.readonly()) {
                this.resetToOrigin();
            }
        });
    }

    ngOnInit(): void {
        this.initForm();
        this.form.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((value) => {
            if (!this.patchingFromJson) {
                this.formValue.set(value);
            }
            this.formSnapshot.set(value);
        });
    }

    initForm(): void {
        const config = this.indexConfig();
        this.form = this.fb.group({
            chunk_strategy: [config?.chunk_strategy || 'tokens', [Validators.required]],
            chunk_size: [config?.chunk_size || 1200, [Validators.required, Validators.min(100), Validators.max(10000)]],
            chunk_overlap: [
                config?.chunk_overlap || 100,
                [Validators.required, Validators.min(0), Validators.max(5000)],
            ],
            entity_types: [config?.entity_types || ['organization', 'person', 'geo', 'event'], [Validators.required]],
            max_gleanings: [config?.max_gleanings || 1, [Validators.required, Validators.min(0), Validators.max(10)]],
            max_cluster_size: [
                config?.max_cluster_size || 10,
                [Validators.required, Validators.min(1), Validators.max(100)],
            ],
        });
        this.formValue.set(this.form.value);
        this.formSnapshot.set(this.form.value);
    }

    resetToOrigin(): void {
        const config = this.indexConfig();
        if (!config) return;
        this.form.patchValue({
            chunk_strategy: config.chunk_strategy,
            chunk_size: config.chunk_size,
            chunk_overlap: config.chunk_overlap,
            entity_types: config.entity_types,
            max_gleanings: config.max_gleanings,
            max_cluster_size: config.max_cluster_size,
        });
    }

    onResetClick(): void {
        this.resetToOrigin();
        this.reset.emit();
    }

    setServerErrors(errors: ApiErrorItem[]): void {
        this.serverErrorsRef.setErrors(errors);
    }

    onJsonValidChange(isValid: boolean): void {
        this.isJsonValid.set(isValid);
    }

    onJsonChange(json: string): void {
        if (!this.isJsonValid()) return;

        try {
            const parsed = JSON.parse(json);
            const formKeys = Object.keys(this.form.controls);
            const patch: Record<string, unknown> = {};

            for (const key of formKeys) {
                if (!(key in parsed)) continue;

                if (key === 'entity_types') {
                    const items = parsed[key];
                    if (!Array.isArray(items) || items.some((t: string) => t.length < 1 || t.length > 20)) {
                        continue;
                    }
                }

                patch[key] = parsed[key];
            }

            this.patchingFromJson = true;
            this.form.patchValue(patch);
            this.form.markAllAsTouched();
            this.patchingFromJson = false;
        } catch {
            // invalid JSON, ignore
        }
    }

    getControl(control: string): AbstractControl | null | undefined {
        return this.form.get(control);
    }
}
