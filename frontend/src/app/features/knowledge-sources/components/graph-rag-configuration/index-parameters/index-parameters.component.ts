import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AbstractControl, FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ChipsInputComponent,
    InputNumberComponent,
    JsonEditorComponent,
    RadioButtonComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { MATERIAL_FORMS } from '@shared/material-forms';

import { GraphRagFileType, GraphRagIndexConfig } from '../../../models/graph-rag.model';

@Component({
    selector: 'app-graph-rag-index-parameters',
    templateUrl: './index-parameters.component.html',
    styleUrls: ['./index-parameters.component.scss'],
    imports: [
        MATERIAL_FORMS,
        RadioButtonComponent,
        ChipsInputComponent,
        InputNumberComponent,
        ReactiveFormsModule,
        ValidationErrorsComponent,
        JsonEditorComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppGraphRagParametersComponent implements OnInit {
    private fb = inject(FormBuilder);
    private destroyRef = inject(DestroyRef);

    indexConfig = input<GraphRagIndexConfig | null>(null);
    selectedFormat = input<GraphRagFileType>('text');

    formValue = signal<Partial<GraphRagIndexConfig> | null>(null);
    jsonData = computed(() => {
        return JSON.stringify({
            file_type: this.selectedFormat(),
            ...this.formValue(),
        });
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
        readOnly: true,
    };
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

    ngOnInit(): void {
        this.initForm();
        this.form.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((value) => this.formValue.set(value));
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
    }

    getControl(control: string): AbstractControl | null | undefined {
        return this.form.get(control);
    }
}
