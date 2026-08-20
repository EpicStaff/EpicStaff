import { ChangeDetectionStrategy, Component, computed, effect, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AppSvgIconComponent } from '@shared/components';
import type { editor as MonacoEditor } from 'monaco-editor';
import { MarkdownModule } from 'ngx-markdown';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';

import { AgentDefinition } from '../../../../models/agent-definition.model';
import { DetailCrumb, DetailHeaderComponent } from '../detail-header/detail-header.component';

type DocMode = 'preview' | 'markdown';

@Component({
    selector: 'app-agent-doc-preview',
    imports: [FormsModule, AppSvgIconComponent, MarkdownModule, MonacoEditorModule, DetailHeaderComponent],
    templateUrl: './agent-doc-preview.component.html',
    styleUrls: ['./agent-doc-preview.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentDocPreviewComponent {
    agent = input.required<AgentDefinition>();
    showSidebar = input<boolean>(true);

    readonly toggleSidebar = output<void>();
    readonly save = output<string>();
    readonly openAgent = output<number>();

    readonly mode = signal<DocMode>('preview');
    readonly draft = signal<string>('');

    readonly fileName = 'Boot_Instructions.md';
    readonly crumbs = computed<DetailCrumb[]>(() => [
        { label: 'AGENTS' },
        { label: this.agent().name, icon: 'agents-tab', navAgentId: this.agent().id },
        { label: this.fileName },
    ]);

    readonly monacoOptions: MonacoEditor.IStandaloneEditorConstructionOptions = {
        theme: 'vs-dark',
        language: 'markdown',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        lineNumbers: 'on',
        tabSize: 2,
    };

    constructor() {
        effect(() => this.draft.set(this.agent().instructions ?? ''));
    }

    setMode(mode: DocMode): void {
        this.mode.set(mode);
    }

    onEditorInit(editor: MonacoEditor.IStandaloneCodeEditor): void {
        editor.onDidBlurEditorText(() => this.onEditorBlur());
    }

    onEditorBlur(): void {
        const value = this.draft();
        if (value === (this.agent().instructions ?? '')) return;
        this.save.emit(value);
    }
}
