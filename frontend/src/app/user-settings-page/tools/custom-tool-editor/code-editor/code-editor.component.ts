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
import { NgIf } from '@angular/common';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';
import { from, of, Subject, Subscription } from 'rxjs';
import {
  catchError,
  debounceTime,
  distinctUntilChanged,
  switchMap,
} from 'rxjs/operators';
import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';
import { IconButtonComponent } from '../../../../shared/components/buttons/icon-button/icon-button.component';
import { ToastService } from '../../../../services/notifications/toast.service';
import { RuffDiagnosticsService } from '../../../../shared/ruff-linter/services/ruff-diagnostics.service';
import { RuffWasmService } from '../../../../shared/ruff-linter/services/ruff-wasm.service';
import type { RuffDiagnostic } from '../../../../shared/ruff-linter/models/ruff-result.model';

const LINT_DEBOUNCE_MS = 400;

@Component({
  selector: 'app-code-editor',
  imports: [
    FormsModule,
    NgIf,
    MonacoEditorModule,
    AppIconComponent,
    IconButtonComponent,
  ],
  templateUrl: './code-editor.component.html',
  styleUrls: ['./code-editor.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  standalone: true,
})
export class CodeEditorComponent implements OnDestroy {
  @ViewChild('editorContainer', { static: true }) editorContainer!: ElementRef;

  @Input() public pythonCode: string = '';
  @Output() public pythonCodeChange = new EventEmitter<string>();
  @Output() public errorChange = new EventEmitter<boolean>();

  private monacoEditor: any = null;
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
          from(this.ruffWasmService.check(code)).pipe(
            catchError(() => of<RuffDiagnostic[]>([]))
          )
        )
      )
      .subscribe({
        next: (diagnostics) => this.applyRuffDiagnostics(diagnostics),
      });
  }

  ngOnDestroy(): void {
    this.lintSubscription?.unsubscribe();
  }

  private applyRuffDiagnostics(diagnostics: RuffDiagnostic[]): void {
    if (this.monacoEditor) {
      this.ruffDiagnosticsService.setMarkers(this.monacoEditor, diagnostics);
    }
    const hasErrors = diagnostics.some(
      (d) => d.code && (d.code.startsWith('E') || d.code.startsWith('F'))
    );
    this.errorChange.emit(hasErrors);
    this.cdr.markForCheck();
  }

  public onCodeChange(newValue: string): void {
    this.pythonCode = newValue;
    this.pythonCodeChange.emit(newValue);
    this.lintCode$.next(newValue);
    this.cdr.markForCheck();
  }

  public onEditorInit(editor: any): void {
    this.editorLoaded = true;
    this.monacoEditor = editor;

    if (this.monacoEditor) {
      this.monacoEditor.updateOptions({
        wordWrapBreakAfterCharacters: ',:',
        wordWrapBreakBeforeCharacters: '}])',
      });
    }

    this.lintCode$.next(this.pythonCode);
    this.cdr.markForCheck();
  }

  public copyCode(): void {
    navigator.clipboard
      .writeText(this.pythonCode)
      .then(() => {
        this.toastService.success(
          'Code copied to clipboard!',
          3000,
          'bottom-right'
        );
      })
      .catch(() => {
        this.toastService.error('Failed to copy code', 3000, 'top-right');
      });
  }
}
