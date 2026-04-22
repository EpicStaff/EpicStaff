import {
    Component,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    NgZone,
    AfterViewInit,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CommonModule } from '@angular/common';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';
import { ICellEditorAngularComp } from 'ag-grid-angular';
import { ICellEditorParams } from 'ag-grid-community';

@Component({
    selector: 'app-monaco-cell-editor',
    standalone: true,
    imports: [CommonModule, FormsModule, MonacoEditorModule],
    template: `
        <div class="monaco-cell-editor">
            <ngx-monaco-editor
                [options]="editorOptions"
                [ngModel]="value"
                (ngModelChange)="onValueChange($event)"
                (onInit)="onEditorInit($event)"
                class="cell-monaco-editor"
            ></ngx-monaco-editor>
        </div>
    `,
    styles: [`
        :host {
            display: block;
        }
        .monaco-cell-editor {
            width: 500px;
            height: 200px;
            border: 1px solid rgba(104, 95, 255, 0.5);
            border-radius: 6px;
            overflow: hidden;
            background: #1e1e1e;
        }
        .cell-monaco-editor {
            width: 100%;
            height: 100%;
        }
        ::ng-deep .monaco-cell-editor .editor-container {
            height: 100% !important;
        }
    `],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MonacoCellEditorComponent implements ICellEditorAngularComp, AfterViewInit {
    public value: string = '';
    private params!: ICellEditorParams;
    private monacoEditor: any;

    public editorOptions = {
        theme: 'vs-dark',
        language: 'python',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on' as const,
        lineNumbers: 'off' as const,
        glyphMargin: false,
        folding: false,
        lineDecorationsWidth: 4,
        lineNumbersMinChars: 0,
        renderLineHighlight: 'none' as const,
        overviewRulerLanes: 0,
        hideCursorInOverviewRuler: true,
        overviewRulerBorder: false,
        scrollbar: {
            vertical: 'auto' as const,
            horizontal: 'hidden' as const,
            verticalScrollbarSize: 6,
        },
        tabSize: 4,
        fontSize: 13,
        padding: { top: 8, bottom: 8 },
    };

    constructor(
        private readonly cdr: ChangeDetectorRef,
        private readonly zone: NgZone,
    ) {}

    agInit(params: ICellEditorParams): void {
        this.params = params;
        this.value = params.value || '';
    }

    getValue(): any {
        return this.value || null;
    }

    isPopup(): boolean {
        return true;
    }

    getPopupPosition(): 'over' | 'under' | undefined {
        return 'under';
    }

    ngAfterViewInit(): void {}

    onValueChange(newValue: string): void {
        this.value = newValue;
        this.cdr.markForCheck();
    }

    onEditorInit(editor: any): void {
        this.monacoEditor = editor;

        // Add Escape key binding to close editor without saving
        editor.addCommand(
            (window as any).monaco.KeyCode.Escape,
            () => {
                this.params.stopEditing(true);
            }
        );

        // Add Ctrl/Cmd+Enter to confirm and close
        editor.addCommand(
            (window as any).monaco.KeyMod.CtrlCmd | (window as any).monaco.KeyCode.Enter,
            () => {
                this.params.stopEditing(false);
            }
        );

        // Focus the editor
        setTimeout(() => editor.focus(), 50);

        this.cdr.markForCheck();
    }
}
