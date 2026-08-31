import { NgIf } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    ElementRef,
    EventEmitter,
    HostBinding,
    Input,
    OnChanges,
    OnDestroy,
    Output,
    SimpleChanges,
    ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import type { editor as MonacoEditor } from 'monaco-editor';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';

import { ToastService } from '../../../services/notifications';
import { ResizableDirective } from '../../../user-settings-page/tools/custom-tool-editor/directives/resizable.directive';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

export interface JsonError {
    line: number;
    column?: number;
    message: string;
}

@Component({
    selector: 'app-json-editor',
    imports: [FormsModule, NgIf, MonacoEditorModule, ResizableDirective, AppSvgIconComponent, MatTooltipModule],
    templateUrl: './json-editor.component.html',
    styleUrls: ['./json-editor.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: true,
})
export class JsonEditorComponent implements OnChanges, OnDestroy {
    @ViewChild('editorContainer', { static: true }) public editorContainer!: ElementRef;

    @Input() public jsonData: string = '{}';
    @Input() public editorHeight: number = 200;
    @Input() public fullHeight: boolean = false;
    @Input() public showHeader: boolean = true;
    @Input() public title: string = 'JSON Editor';
    @Input() public subtitle: string = '';
    @Input() public collapsible: boolean = false;
    @Input() public allowCopy: boolean = false;
    @Input() public allowExpand: boolean = false;
    @Input() public jsonSchema?: object;
    @Input() public extraValidate?: (json: string) => { message: string; startOffset: number; endOffset: number }[];
    @Input() public exampleHint: string = '';
    @Input() public editorOptions: MonacoEditor.IStandaloneEditorConstructionOptions = {
        theme: 'vs-dark',
        language: 'json',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        wrappingIndent: 'indent',
        wordWrapBreakAfterCharacters: ',',
        wordWrapBreakBeforeCharacters: '}]',
        formatOnPaste: true,
        formatOnType: true,
        tabSize: 2,
        readOnly: false,
    };

    @Output() public jsonChange = new EventEmitter<string>();
    @Output() public validationChange = new EventEmitter<boolean>();
    @Output() public errorsChange = new EventEmitter<JsonError[]>();
    @Output() public editorReady = new EventEmitter<MonacoEditor.IStandaloneCodeEditor>();
    @Output() public expand = new EventEmitter<void>();

    public collapsed: boolean = true;
    public editorLoaded = false;
    public jsonIsValid = true;
    public exampleCollapsed = false;

    private monacoEditor: MonacoEditor.IStandaloneCodeEditor | null = null;
    private isProgrammaticChange: boolean = false;
    private lastExternalValue: string = '{}';

    private static schemaSeq = 0;
    private readonly schemaId = `inmemory://json-editor-schema/${JsonEditorComponent.schemaSeq++}.json`;
    private markersDisposable: { dispose(): void } | null = null;

    // Font metrics mirrored once from the live Monaco instance
    public hintFontFamily: string = '';
    public hintFontSize: number = 14;

    public get showExampleHint(): boolean {
        return !!this.exampleHint && this.editorLoaded;
    }

    private get monacoGlobal(): typeof import('monaco-editor') | null {
        return (window as unknown as { monaco?: typeof import('monaco-editor') }).monaco ?? null;
    }

    private get schemaMode(): boolean {
        return !!this.jsonSchema && !!this.monacoGlobal;
    }

    private get usesMarkers(): boolean {
        return (!!this.jsonSchema || !!this.extraValidate) && !!this.monacoGlobal;
    }

    @HostBinding('class.collapsed')
    get hostCollapsed() {
        return this.collapsible && this.collapsed;
    }

    constructor(
        private cdr: ChangeDetectorRef,
        private toast: ToastService
    ) {}

    ngOnChanges(changes: SimpleChanges): void {
        if (!changes['jsonData']) {
            return;
        }

        const newValue = changes['jsonData'].currentValue;
        const isFirst = changes['jsonData'].firstChange;

        if (isFirst && this.monacoEditor && newValue && newValue !== '{}') {
            this.lastExternalValue = newValue;
            this.setValueAndFormat(newValue);
            this.cdr.markForCheck();
        } else if (!isFirst && this.monacoEditor && newValue !== this.lastExternalValue) {
            this.lastExternalValue = newValue;
            this.setValueAndFormat(newValue || '{}');
            this.cdr.markForCheck();
        }
    }

    public onEditorInit(editor: MonacoEditor.IStandaloneCodeEditor): void {
        this.editorLoaded = true;
        this.monacoEditor = editor;
        this.lastExternalValue = this.jsonData;
        this.monacoEditor.updateOptions(this.editorOptions);
        this.setValueAndFormat(this.jsonData || '{}');
        this.editorReady.emit(editor);
        if (this.usesMarkers) {
            if (this.schemaMode) {
                this.registerSchema();
            }
            this.setupMarkerListener();
            this.runExtraValidation();
            this.emitMarkers();
        }
        if (this.exampleHint) {
            this.captureHintMetrics();
        }
        this.cdr.markForCheck();
    }

    public ngOnDestroy(): void {
        this.markersDisposable?.dispose();
        this.unregisterSchema();
    }

    public onJsonChange(newValue: string): void {
        if (this.isProgrammaticChange) {
            return;
        }

        this.lastExternalValue = newValue;

        try {
            JSON.parse(newValue);
            this.jsonIsValid = true;
            if (!this.usesMarkers) {
                this.errorsChange.emit([]);
            }
        } catch (e) {
            this.jsonIsValid = false;
            if (!this.usesMarkers) {
                this.errorsChange.emit([this.buildJsonError(newValue, e)]);
            }
        }

        if (this.usesMarkers) {
            this.runExtraValidation();
        }

        this.validationChange.emit(this.jsonIsValid);
        this.jsonChange.emit(newValue);
        this.cdr.markForCheck();
    }

    public onToggle(): void {
        this.collapsed = !this.collapsed;
    }

    public onToggleExample(): void {
        this.exampleCollapsed = !this.exampleCollapsed;
    }

    private buildJsonError(raw: string, err: unknown): JsonError {
        const message = err instanceof Error ? err.message : String(err);

        const lineCol = message.match(/line (\d+) column (\d+)/i);
        if (lineCol) {
            return {
                line: Number(lineCol[1]),
                column: Number(lineCol[2]),
                message: this.cleanJsonErrorMessage(message),
            };
        }

        const posMatch = message.match(/at position (\d+)/i);
        if (posMatch) {
            const pos = Number(posMatch[1]);
            const upto = raw.slice(0, pos);
            const line = 1 + (upto.match(/\n/g)?.length ?? 0);
            const column = pos - raw.lastIndexOf('\n', pos - 1);
            return { line, column, message: this.cleanJsonErrorMessage(message) };
        }

        return { line: 1, column: 1, message: this.cleanJsonErrorMessage(message) };
    }

    private cleanJsonErrorMessage(message: string): string {
        const cleaned = message.replace(/\s*in JSON at position.*$/i, '').trim();
        return cleaned || message;
    }

    public onCopy(): void {
        navigator.clipboard.writeText(this.jsonData).then(() => {
            this.toast.success('Copied to clipboard!');
        });
    }

    public onExpand(): void {
        this.expand.emit();
    }

    public onResize(newHeight: number): void {
        this.editorHeight = newHeight;
        this.monacoEditor?.layout();
    }

    public formatJson(): void {
        this.monacoEditor?.getAction('editor.action.formatDocument')?.run();
    }

    private registerSchema(): void {
        const monaco = this.monacoGlobal;
        const modelUri = this.monacoEditor?.getModel()?.uri?.toString();
        if (!monaco?.languages?.json || !modelUri) {
            return;
        }
        const defaults = monaco.languages.json.jsonDefaults;
        const current = defaults.diagnosticsOptions?.schemas ?? [];
        const others = current.filter((s: { uri?: string }) => s.uri !== this.schemaId);
        defaults.setDiagnosticsOptions({
            ...defaults.diagnosticsOptions,
            validate: true,
            schemaValidation: 'error',
            schemas: [...others, { uri: this.schemaId, fileMatch: [modelUri], schema: this.jsonSchema }],
        });
    }

    private unregisterSchema(): void {
        const monaco = this.monacoGlobal;
        if (!monaco?.languages?.json) {
            return;
        }
        const defaults = monaco.languages.json.jsonDefaults;
        const current = defaults.diagnosticsOptions?.schemas ?? [];
        defaults.setDiagnosticsOptions({
            ...defaults.diagnosticsOptions,
            schemas: current.filter((s: { uri?: string }) => s.uri !== this.schemaId),
        });
    }

    private setupMarkerListener(): void {
        const monaco = this.monacoGlobal;
        if (!monaco?.editor?.onDidChangeMarkers) {
            return;
        }
        this.markersDisposable = monaco.editor.onDidChangeMarkers((uris) => {
            const myUri = this.monacoEditor?.getModel()?.uri?.toString();
            if (myUri && uris.some((u) => u.toString() === myUri)) {
                this.emitMarkers();
            }
        });
    }

    private emitMarkers(): void {
        const monaco = this.monacoGlobal;
        const model = this.monacoEditor?.getModel();
        if (!monaco?.editor || !model) {
            return;
        }
        const markers = monaco.editor.getModelMarkers({ resource: model.uri }) as Array<{
            severity: number;
            startLineNumber: number;
            startColumn: number;
            message: string;
        }>;
        const errorSeverity = monaco.MarkerSeverity?.Error ?? 8;
        const seen = new Set<string>();
        const errors: JsonError[] = [];
        for (const m of markers) {
            if (m.severity !== errorSeverity) {
                continue;
            }
            const key = `${m.startLineNumber}:${m.startColumn}:${m.message}`;
            if (seen.has(key)) {
                continue;
            }
            seen.add(key);
            errors.push({ line: m.startLineNumber, column: m.startColumn, message: m.message });
        }
        errors.sort((a, b) => a.line - b.line || (a.column ?? 0) - (b.column ?? 0));
        this.errorsChange.emit(errors);
        this.cdr.markForCheck();
    }

    private runExtraValidation(): void {
        const monaco = this.monacoGlobal;
        const model = this.monacoEditor?.getModel();
        if (!this.extraValidate || !monaco?.editor || !model) {
            return;
        }
        const markers = this.extraValidate(model.getValue()).map((m) => {
            const start = model.getPositionAt(m.startOffset);
            const end = model.getPositionAt(m.endOffset);
            return {
                severity: monaco.MarkerSeverity?.Error ?? 8,
                message: m.message,
                startLineNumber: start.lineNumber,
                startColumn: start.column,
                endLineNumber: end.lineNumber,
                endColumn: end.column,
            };
        });
        monaco.editor.setModelMarkers(model, 'json-editor-extra', markers);
    }

    private captureHintMetrics(): void {
        const monaco = this.monacoGlobal;
        if (!monaco?.editor?.EditorOption || !this.monacoEditor) {
            return;
        }
        const fontInfo = this.monacoEditor.getOption(monaco.editor.EditorOption.fontInfo) as {
            fontFamily: string;
            fontSize: number;
        };
        this.hintFontFamily = fontInfo.fontFamily;
        this.hintFontSize = fontInfo.fontSize;
        this.cdr.markForCheck();
    }

    private setValueAndFormat(value: string): void {
        this.isProgrammaticChange = true;
        this.monacoEditor?.setValue(value);
        if (!this.jsonIsValid) {
            this.jsonIsValid = true;
            this.validationChange.emit(true);
            if (!this.usesMarkers) {
                this.errorsChange.emit([]);
            }
        }
        const formatting = this.monacoEditor?.getAction('editor.action.formatDocument')?.run();
        const release = () => {
            this.isProgrammaticChange = false;
            this.runExtraValidation();
        };
        if (formatting && typeof formatting.then === 'function') {
            formatting.then(release, release);
        } else {
            release();
        }
    }
}
