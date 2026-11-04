import { ChangeDetectionStrategy, Component, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import type { editor as MonacoEditor } from 'monaco-editor';
import { MarkdownComponent } from 'ngx-markdown';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';

import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { AgentDefinition, AgentInstruction } from '../../../../models/agent-definition.model';
import { DetailCrumb, DetailHeaderComponent } from '../detail-header/detail-header.component';

type DocMode = 'preview' | 'markdown';

@Component({
    selector: 'app-agent-doc-preview',
    imports: [
        FormsModule,
        AppSvgIconComponent,
        MarkdownComponent,
        MonacoEditorModule,
        DetailHeaderComponent,
        HasPermissionDirective,
    ],
    templateUrl: './agent-doc-preview.component.html',
    styleUrls: ['./agent-doc-preview.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentDocPreviewComponent {
    private readonly permissionService = inject(PermissionsService);

    /** Built by the page, which owns the group crumb shared with the agent and surface views. */
    crumbs = input.required<DetailCrumb[]>();
    agent = input.required<AgentDefinition>();
    instruction = input.required<AgentInstruction>();
    showSidebar = input<boolean>(true);
    initialEditMode = input<boolean>(false);

    /** The edited instruction's new content; the parent saves it into `instruction_list`. */
    readonly save = output<string>();
    readonly toggleSidebar = output<void>();
    readonly openAgent = output<number>();
    readonly openAgentInstructions = output<number>();
    /** Picked in the group crumb: moves the agent (a group id, or null for Ungrouped). */
    readonly groupChange = output<number | null>();

    readonly mode = signal<DocMode>('preview');
    readonly draft = signal<string>('');

    private initialModeApplied = false;

    constructor() {
        effect(() => this.draft.set(this.instruction().content));
        effect(() => {
            const edit = this.initialEditMode();
            if (!this.initialModeApplied) {
                this.initialModeApplied = true;
                const canEdit = this.permissionService.can(ResourceCode.Agents, ActionCode.Update);
                if (edit && canEdit) this.mode.set('markdown');
            }
        });
    }

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

    setMode(mode: DocMode): void {
        this.mode.set(mode);
    }

    onEditorInit(editor: MonacoEditor.IStandaloneCodeEditor): void {
        editor.onDidBlurEditorText(() => this.onEditorBlur());
    }

    onEditorBlur(): void {
        const value = this.draft();
        if (value === this.instruction().content) return;
        this.save.emit(value);
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
