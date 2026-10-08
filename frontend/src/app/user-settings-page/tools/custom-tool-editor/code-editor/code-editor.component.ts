import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    ElementRef,
    EventEmitter,
    Input,
    input,
    NgZone,
    OnChanges,
    OnDestroy,
    Output,
    output,
    SimpleChanges,
    ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, IconButtonComponent } from '@shared/components';
import type { editor as MonacoEditor } from 'monaco-editor';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';
import { from, of, Subject, Subscription } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import type { RuffDiagnostic } from '../../../../shared/ruff-linter/models/ruff-result.model';
import { RuffDiagnosticsService } from '../../../../shared/ruff-linter/services/ruff-diagnostics.service';
import { RuffWasmService } from '../../../../shared/ruff-linter/services/ruff-wasm.service';

const LINT_DEBOUNCE_MS = 400;

@Component({
    selector: 'app-code-editor',
    imports: [FormsModule, MonacoEditorModule, AppSvgIconComponent, IconButtonComponent, MatTooltipModule],
    templateUrl: './code-editor.component.html',
    styleUrls: ['./code-editor.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        '[class.fixed-height]': 'editorHeight() !== null',
    },
})
export class CodeEditorComponent implements OnChanges, OnDestroy {
    @ViewChild('editorContainer', { static: true }) editorContainer!: ElementRef;

    @Input() public pythonCode: string = '';
    @Input() public showHeader: boolean = true;
    @Input() public secretNames: string[] = [];
    @Input() public inputMapKeys: string[] = [];
    @Input() public readOnly: boolean = false;
    @Output() public pythonCodeChange = new EventEmitter<string>();
    @Output() public errorChange = new EventEmitter<boolean>();
    /**
     * Opt-in fixed editor height in px. Unset (null) keeps the default behaviour: the editor fills
     * its host.
     */
    public readonly editorHeight = input<number | null>(null);
    /** Shows an expand icon next to copy in the header; clicking it emits `expand`. */
    public readonly allowExpand = input(false);
    /** Label and tooltip of the expand icon; a host whose expand does something else (e.g. swaps panes) names it. */
    public readonly expandLabel = input('Expand editor');
    /**
     * Renders the header like the JSON editor's (muted entrypoint subtitle, small bare action icons), for a
     * host that shows this editor next to a JSON editor. Off: the default header with bordered icon buttons.
     */
    public readonly compactHeader = input(false);
    public readonly expand = output<void>();
    /**
     * Opt-in extra icon in the compact header (a sprite icon name), placed before the copy icon and styled
     * like it, as in the JSON editor. It renders only with both `actionIcon` and `actionLabel` (its aria-label
     * and tooltip) set. The default header has no slot for it.
     */
    public readonly actionIcon = input<string | null>(null);
    public readonly actionLabel = input<string | null>(null);
    /** Why the action cannot be used right now (its tooltip then); null enables it. */
    public readonly actionDisabledReason = input<string | null>(null);
    public readonly action = output<void>();

    protected readonly headerAction = computed(() => {
        const icon = this.actionIcon();
        const label = this.actionLabel();
        return icon && label ? { icon, label } : null;
    });
    protected readonly isActionDisabled = computed(() => this.actionDisabledReason() !== null);
    protected readonly actionTooltip = computed(() => this.actionDisabledReason() ?? this.actionLabel() ?? '');

    private monacoEditor: import('monaco-editor').editor.IStandaloneCodeEditor | null = null;
    private completionDisposable: import('monaco-editor').IDisposable | null = null;
    private readonly lintCode$ = new Subject<string>();
    private lintSubscription: Subscription | null = null;
    private containerResizeObserver: ResizeObserver | null = null;

    public editorLoaded = false;

    public editorOptions: MonacoEditor.IStandaloneEditorConstructionOptions = {
        theme: 'vs-dark',
        language: 'python',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        wrappingIndent: 'indent',
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
        this.containerResizeObserver?.disconnect();
    }

    private applyRuffDiagnostics(diagnostics: RuffDiagnostic[]): void {
        if (this.monacoEditor) {
            this.ruffDiagnosticsService.setMarkers(this.monacoEditor, diagnostics);
        }
        this.errorChange.emit(this.ruffDiagnosticsService.hasSyntaxErrors(diagnostics));
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
                readOnly: this.readOnly,
            });
        }

        this.registerSecretCompletions();
        this.observeContainerResize();

        this.lintCode$.next(this.pythonCode);
        this.cdr.markForCheck();
    }

    private observeContainerResize(): void {
        this.zone.runOutsideAngular(() => {
            this.containerResizeObserver = new ResizeObserver(() => {
                this.monacoEditor?.layout();
            });
            this.containerResizeObserver.observe(this.editorContainer.nativeElement);
        });
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['readOnly'] && !changes['readOnly'].firstChange) {
            this.monacoEditor?.updateOptions({ readOnly: this.readOnly });
        }
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

    protected onExpand(): void {
        this.expand.emit();
    }

    protected onAction(): void {
        if (this.isActionDisabled()) return;
        this.action.emit();
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
