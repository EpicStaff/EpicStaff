import { NgIf } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    ElementRef,
    EventEmitter,
    Input,
    NgZone,
    OnDestroy,
    Output,
    ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';
import { from, of, Subject, Subscription } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { IconButtonComponent } from '../../../../shared/components/buttons/icon-button/icon-button.component';
import type { RuffDiagnostic } from '../../../../shared/ruff-linter/models/ruff-result.model';
import { RuffDiagnosticsService } from '../../../../shared/ruff-linter/services/ruff-diagnostics.service';
import { RuffWasmService } from '../../../../shared/ruff-linter/services/ruff-wasm.service';

const LINT_DEBOUNCE_MS = 400;

@Component({
    selector: 'app-code-editor',
    imports: [FormsModule, NgIf, MonacoEditorModule, AppSvgIconComponent, IconButtonComponent, MatTooltipModule],
    templateUrl: './code-editor.component.html',
    styleUrls: ['./code-editor.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: true,
})
export class CodeEditorComponent implements OnDestroy {
    @ViewChild('editorContainer', { static: true }) editorContainer!: ElementRef;

    @Input() public pythonCode: string = '';
    @Input() public showHeader: boolean = true;
    @Input() public secretNames: string[] = [];
    @Input() public inputMapKeys: string[] = [];
    @Output() public pythonCodeChange = new EventEmitter<string>();
    @Output() public errorChange = new EventEmitter<boolean>();

    private monacoEditor: import('monaco-editor').editor.IStandaloneCodeEditor | null = null;
    private completionDisposable: import('monaco-editor').IDisposable | null = null;
    private readonly lintCode$ = new Subject<string>();
    private lintSubscription: Subscription | null = null;

    public editorLoaded = false;

    public editorOptions = {
        theme: 'vs-dark',
        language: 'python',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        wrappingIndent: 'indent',
        wordWrapMinified: true,
        formatOnPaste: true,
        formatOnType: true,
        tabSize: 4,
    };

    constructor(
        private readonly cdr: ChangeDetectorRef,
        private readonly zone: NgZone,
        private readonly toastService: ToastService,
        private readonly ruffWasmService: RuffWasmService,
        private readonly ruffDiagnosticsService: RuffDiagnosticsService
    ) {
        this.lintSubscription = this.lintCode$
            .pipe(
                debounceTime(LINT_DEBOUNCE_MS),
                distinctUntilChanged(),
                switchMap((code) =>
                    from(this.ruffWasmService.check(code)).pipe(catchError(() => of<RuffDiagnostic[]>([])))
                )
            )
            .subscribe({
                next: (diagnostics) => this.applyRuffDiagnostics(diagnostics),
            });
    }

    ngOnDestroy(): void {
        this.lintSubscription?.unsubscribe();
        this.completionDisposable?.dispose();
    }

    private applyRuffDiagnostics(diagnostics: RuffDiagnostic[]): void {
        if (this.monacoEditor) {
            this.ruffDiagnosticsService.setMarkers(this.monacoEditor, diagnostics);
        }
        const hasErrors = diagnostics.some((d) => d.code && (d.code.startsWith('E') || d.code.startsWith('F')));
        this.errorChange.emit(hasErrors);
        this.cdr.markForCheck();
    }

    public onCodeChange(newValue: string): void {
        this.pythonCode = newValue;
        this.pythonCodeChange.emit(newValue);
        this.lintCode$.next(newValue);
        this.cdr.markForCheck();
    }

    public onEditorInit(editor: import('monaco-editor').editor.IStandaloneCodeEditor): void {
        this.editorLoaded = true;
        this.monacoEditor = editor;

        if (this.monacoEditor) {
            this.monacoEditor.updateOptions({
                wordWrapBreakAfterCharacters: ',:',
                wordWrapBreakBeforeCharacters: '}])',
            });
        }

        this.registerSecretCompletions();

        this.lintCode$.next(this.pythonCode);
        this.cdr.markForCheck();
    }

    private registerSecretCompletions(): void {
        const monaco = (window as unknown as { monaco?: typeof import('monaco-editor') }).monaco;
        if (!monaco) return;

        this.completionDisposable = monaco.languages.registerCompletionItemProvider('python', {
            provideCompletionItems: (model, position) => {
                if (
                    (!this.secretNames.length && !this.inputMapKeys.length) ||
                    model !== this.monacoEditor?.getModel()
                ) {
                    return { suggestions: [] };
                }
                const word = model.getWordUntilPosition(position);
                const range = {
                    startLineNumber: position.lineNumber,
                    endLineNumber: position.lineNumber,
                    startColumn: word.startColumn,
                    endColumn: word.endColumn,
                };
                return {
                    suggestions: [
                        ...this.inputMapKeys.map((name) => ({
                            label: name,
                            kind: monaco.languages.CompletionItemKind.Variable,
                            detail: 'Input List argument',
                            insertText: name,
                            range,
                        })),
                        ...this.secretNames.map((name) => ({
                            label: name,
                            kind: monaco.languages.CompletionItemKind.Constant,
                            detail: `get_secret("${name}")`,
                            insertText: `get_secret("${name}")`,
                            range,
                        })),
                    ],
                };
            },
        });
    }

    public copyCode(): void {
        navigator.clipboard
            .writeText(this.pythonCode)
            .then(() => {
                this.toastService.success('Code copied to clipboard!', 3000, 'bottom-right');
            })
            .catch(() => {
                this.toastService.error('Failed to copy code', 3000, 'top-right');
            });
    }
}
