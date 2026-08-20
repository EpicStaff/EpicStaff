import { NgIf } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    output,
    signal,
    ViewChild,
} from '@angular/core';
import {
    DDL_LANGUAGE_ID,
    type Diagnostic,
    diagnosticsToMarkers,
    ensureDdlLanguageRegistered,
    generate,
    type GenerateResult,
} from '@shared/ddl';
import type { editor as MonacoEditor, IDisposable } from 'monaco-editor';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';

/** Owner id passed to `setModelMarkers` so DDL markers don't clash with other providers on the same model. */
const DDL_MARKERS_OWNER = 'epicstaff-ddl';

/** Debounce between the last keystroke and re-running `generate()`. */
const COMPILE_DEBOUNCE_MS = 150;

/** The `monaco` global only exists once `ngx-monaco-editor-v2` has lazily loaded it. */
function getMonacoNamespace(): typeof import('monaco-editor') | null {
    return (window as unknown as { monaco?: typeof import('monaco-editor') }).monaco ?? null;
}

/**
 * DDL source editor. Owns the Monaco text model directly (no `ngModel`) so
 * external pushes of `value()` — e.g. from a live JSON⇄DDL sync — can be
 * applied via `pushEditOperations` (preserving undo/cursor) instead of a
 * blunt `setValue`, and so they never echo back out through `valueChange`.
 */
@Component({
    selector: 'app-ddl-editor',
    standalone: true,
    imports: [NgIf, MonacoEditorModule],
    templateUrl: './ddl-editor.component.html',
    styleUrls: ['./ddl-editor.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DdlEditorComponent {
    // Inputs / Outputs
    readonly value = input<string>('');
    readonly valueChange = output<string>();
    readonly diagnosticsChange = output<Diagnostic[]>();
    readonly schemaChange = output<GenerateResult>();
    readonly editorReady = output<MonacoEditor.IStandaloneCodeEditor>();

    // ViewChild
    @ViewChild('editorContainer', { static: true }) editorContainer!: ElementRef<HTMLDivElement>;

    // Signals & Computed
    readonly editorLoaded = signal(false);

    // Effects
    private readonly applyExternalValueEffect = effect(() => {
        const nextValue = this.value();
        if (!this.editorLoaded()) return;

        const model = this.monacoEditor?.getModel();
        if (!model || model.getValue() === nextValue) return;

        // Monaco's pushEditOperations is synchronous: onDidChangeContent fires before it returns, so the flag is still true when the listener checks it.
        this.applyingExternalValue = true;
        model.pushEditOperations([], [{ range: model.getFullModelRange(), text: nextValue }], () => null);
        this.applyingExternalValue = false;
    });

    // Public template-bound properties
    readonly editorOptions: MonacoEditor.IStandaloneEditorConstructionOptions = {
        theme: 'vs-dark',
        automaticLayout: true,
        minimap: { enabled: false },
        wordWrap: 'off',
        tabSize: 2,
        insertSpaces: true,
    };

    // Private fields
    private readonly destroyRef = inject(DestroyRef);
    private monacoEditor: MonacoEditor.IStandaloneCodeEditor | null = null;
    private compileTimeoutId: ReturnType<typeof setTimeout> | null = null;
    private contentChangeListener: IDisposable | null = null;
    /** True only for the duration of a programmatic model write — swallows the resulting `valueChange` echo. */
    private applyingExternalValue = false;

    constructor() {
        this.destroyRef.onDestroy(() => {
            this.clearPendingCompile();
            this.contentChangeListener?.dispose();
        });
    }

    // Public methods
    onEditorInit(editor: MonacoEditor.IStandaloneCodeEditor): void {
        this.monacoEditor = editor;

        const monacoNs = getMonacoNamespace();
        const model = editor.getModel();
        if (monacoNs && model) {
            ensureDdlLanguageRegistered(monacoNs);
            monacoNs.editor.setModelLanguage(model, DDL_LANGUAGE_ID);
        }

        if (model) {
            this.applyingExternalValue = true;
            model.setValue(this.value());
            this.applyingExternalValue = false;

            this.contentChangeListener = model.onDidChangeContent(() => {
                const source = model.getValue();
                if (!this.applyingExternalValue) {
                    this.valueChange.emit(source);
                }
                this.scheduleCompile(source);
            });
        }

        this.editorLoaded.set(true);
        this.editorReady.emit(editor);
        this.runCompile(this.value());
    }

    // Private methods
    private scheduleCompile(source: string): void {
        this.clearPendingCompile();
        this.compileTimeoutId = setTimeout(() => this.runCompile(source), COMPILE_DEBOUNCE_MS);
    }

    private clearPendingCompile(): void {
        if (this.compileTimeoutId !== null) {
            clearTimeout(this.compileTimeoutId);
            this.compileTimeoutId = null;
        }
    }

    private runCompile(source: string): void {
        const result = generate(source);
        this.publishMarkers(result.schema.diagnostics);
        this.diagnosticsChange.emit(result.schema.diagnostics);
        this.schemaChange.emit(result);
    }

    private publishMarkers(diagnostics: Diagnostic[]): void {
        const monacoNs = getMonacoNamespace();
        const model = this.monacoEditor?.getModel();
        if (!monacoNs || !model) {
            return;
        }
        monacoNs.editor.setModelMarkers(model, DDL_MARKERS_OWNER, diagnosticsToMarkers(diagnostics, model));
    }
}
