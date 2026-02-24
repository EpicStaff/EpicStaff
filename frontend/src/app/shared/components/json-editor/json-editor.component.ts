import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  NgZone,
  OnChanges,
  OnDestroy,
  Output,
  SimpleChanges,
  HostBinding,
  ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgIf } from '@angular/common';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';
import { ResizableDirective } from '../../../user-settings-page/tools/custom-tool-editor/directives/resizable.directive';
import { AppIconComponent } from "../app-icon/app-icon.component";
import { ToastService } from "../../../services/notifications";

@Component({
  selector: 'app-json-editor',
  imports: [FormsModule, NgIf, MonacoEditorModule, ResizableDirective, AppIconComponent],
  templateUrl: './json-editor.component.html',
  styleUrls: ['./json-editor.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  standalone: true,
})
export class JsonEditorComponent implements OnChanges {
  @ViewChild('editorContainer', { static: true }) editorContainer!: ElementRef;

  @Input() public jsonData: string = '{}';
  @Input() public editorHeight: number = 200;
  @Input() public fullHeight: boolean = false;
  @Input() public showHeader: boolean = true;
  @Input() public title: string = 'JSON Editor';
  @Input() public collapsible: boolean = false;
  @Input() public allowCopy : boolean = false;

  public collapsed: boolean = true;
  public editorLoaded = false;
  private lastExternalValue: string = '{}';
  private isUserTyping: boolean = false;
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

  @HostBinding('class.collapsed')
  get hostCollapsed() {
    return this.collapsible && this.collapsed;
  }

  constructor(private cdr: ChangeDetectorRef, private zone: NgZone, private toast: ToastService) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['jsonData']) {
      const newValue = changes['jsonData'].currentValue;
      const isFirst = changes['jsonData'].firstChange;

      // Skip setValue if the change came from user typing (prevents cursor jump)
      if (this.isUserTyping) {
        return;
      }

      // On first change, if editor exists, set the value directly
      if (isFirst && this.monacoEditor && newValue && newValue !== '{}') {
        this.lastExternalValue = newValue;
        this.monacoEditor.setValue(newValue);
        setTimeout(() => this.monacoEditor?.getAction('editor.action.formatDocument')?.run(), 50);
        this.cdr.markForCheck();
      }
      // On subsequent changes from external sources
      else if (!isFirst && this.monacoEditor && newValue !== this.lastExternalValue) {
        this.lastExternalValue = newValue;
        this.monacoEditor.setValue(newValue || '{}');
        setTimeout(() => {
          this.monacoEditor?.getAction('editor.action.formatDocument')?.run();
        }, 50);
        this.cdr.markForCheck();
      }
    }
  }

  public onJsonChange(newValue: string): void {
    // Mark that user is typing to prevent cursor jump
    this.isUserTyping = true;
    this.lastExternalValue = newValue;

    try {
      JSON.parse(newValue);
      this.jsonIsValid = true;
    } catch (e) {
      this.jsonIsValid = false;
    }

    this.validationChange.emit(this.jsonIsValid);
    this.jsonChange.emit(newValue);
    this.cdr.markForCheck();

    // Reset the flag after a short delay to allow ngOnChanges to skip
    setTimeout(() => {
      this.isUserTyping = false;
    }, 50);
  }

  public onEditorInit(editor: any): void {
    this.editorLoaded = true;
    this.monacoEditor = editor;
    this.lastExternalValue = this.jsonData;

    if (this.monacoEditor) {
      this.monacoEditor.updateOptions(this.editorOptions);
      this.monacoEditor.setValue(this.jsonData || '{}');

      setTimeout(() => {
        this.monacoEditor?.getAction('editor.action.formatDocument')?.run();
      }, 100);
    }

    this.cdr.markForCheck();
  }

  public onToggle() {
      this.collapsed = !this.collapsed;
  }

  public onCopy() {
    navigator.clipboard.writeText(this.jsonData).then(() => {
      this.toast.success('Copied to clipboard!');
    });
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
