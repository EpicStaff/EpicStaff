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
import { ResizableDirective } from '../../../user-settings-page/tools/custom-tool-editor/directives/resizable.directive';

@Component({
  selector: 'app-json-editor',
  imports: [FormsModule, NgIf, MonacoEditorModule, ResizableDirective],
  templateUrl: './json-editor.component.html',
  styleUrls: ['./json-editor.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  standalone: true,
})
export class JsonEditorComponent {
  @ViewChild('editorContainer', { static: true }) editorContainer!: ElementRef;

  @Input() public jsonData: string = '{}';
  @Input() public editorHeight: number = 200;
  @Input() public fullHeight: boolean = false;

  public editorLoaded = false;
  @Output() public jsonChange = new EventEmitter<string>();
  @Output() public validationChange = new EventEmitter<boolean>();

  private monacoEditor: any;
  public jsonIsValid = true;

  @Input() public editorOptions: any = {
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

  constructor(private cdr: ChangeDetectorRef, private zone: NgZone) {}

  public onJsonChange(newValue: string): void {
    try {
      // Try to parse the JSON to check if it's valid
      JSON.parse(newValue);
      this.jsonIsValid = true;
    } catch (e) {
      this.jsonIsValid = false;
    }

    this.validationChange.emit(this.jsonIsValid);
    this.jsonChange.emit(newValue);
    this.cdr.markForCheck();
  }

  public onEditorInit(editor: any): void {
    this.editorLoaded = true;
    this.monacoEditor = editor;

    // Update options based on input properties
    if (this.monacoEditor) {
      this.monacoEditor.updateOptions(this.editorOptions);

      // Format the document on initial load
      setTimeout(() => {
        this.monacoEditor.getAction('editor.action.formatDocument').run();
      }, 100);
    }

    this.cdr.markForCheck();
  }

  /**
   * Called by the resizable directive whenever the user drags the resize handle.
   */
  public onResize(newHeight: number): void {
    this.editorHeight = newHeight;
    if (this.monacoEditor && typeof this.monacoEditor.layout === 'function') {
      this.monacoEditor.layout();
    }
  }

  public formatJson(): void {
    if (this.monacoEditor) {
      this.monacoEditor.getAction('editor.action.formatDocument').run();
    }
  }
}
