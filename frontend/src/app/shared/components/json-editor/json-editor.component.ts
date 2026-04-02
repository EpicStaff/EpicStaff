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
    Output,
    SimpleChanges,
    ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { editor as MonacoEditor } from 'monaco-editor';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';

import { ToastService } from '../../../services/notifications';
import { ResizableDirective } from '../../../user-settings-page/tools/custom-tool-editor/directives/resizable.directive';
import { AppIconComponent } from '../app-icon/app-icon.component';

@Component({
    selector: 'app-json-editor',
    imports: [FormsModule, NgIf, MonacoEditorModule, ResizableDirective, AppIconComponent],
    templateUrl: './json-editor.component.html',
    styleUrls: ['./json-editor.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: true,
})
export class JsonEditorComponent implements OnChanges {
    @ViewChild('editorContainer', { static: true }) public editorContainer!: ElementRef;

    @Input() public jsonData: string = '{}';
    @Input() public editorHeight: number = 200;
    @Input() public fullHeight: boolean = false;
    @Input() public showHeader: boolean = true;
    @Input() public title: string = 'JSON Editor';
    @Input() public collapsible: boolean = false;
    @Input() public allowCopy: boolean = false;
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
    @Output() public editorReady = new EventEmitter<MonacoEditor.IStandaloneCodeEditor>();

    public collapsed: boolean = true;
    public editorLoaded = false;
    public jsonIsValid = true;

    private monacoEditor: MonacoEditor.IStandaloneCodeEditor | null = null;
    private isProgrammaticChange: boolean = false;
    private lastExternalValue: string = '{}';

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
        this.cdr.markForCheck();
    }

    public onJsonChange(newValue: string): void {
        if (this.isProgrammaticChange) {
            return;
        }

        this.lastExternalValue = newValue;

        try {
            JSON.parse(newValue);
            this.jsonIsValid = true;
        } catch {
            this.jsonIsValid = false;
        }

        this.validationChange.emit(this.jsonIsValid);
        this.jsonChange.emit(newValue);
        this.cdr.markForCheck();
    }

    public onToggle(): void {
        this.collapsed = !this.collapsed;
    }

    public onCopy(): void {
        navigator.clipboard.writeText(this.jsonData).then(() => {
            this.toast.success('Copied to clipboard!');
        });
    }

    public onResize(newHeight: number): void {
        this.editorHeight = newHeight;
        this.monacoEditor?.layout();
    }

    public formatJson(): void {
        this.monacoEditor?.getAction('editor.action.formatDocument')?.run();
    }

    private setValueAndFormat(value: string): void {
        this.isProgrammaticChange = true;
        this.monacoEditor?.setValue(value);
        this.monacoEditor
            ?.getAction('editor.action.formatDocument')
            ?.run()
            ?.then(() => {
                this.isProgrammaticChange = false;
            });
    }
}
