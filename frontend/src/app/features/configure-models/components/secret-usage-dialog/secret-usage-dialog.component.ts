import { animate, state, style, transition, trigger } from '@angular/animations';
import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ComponentType } from '@angular/cdk/overlay';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import {
    AppSvgIconComponent,
    ButtonComponent,
    EmbeddingModelConfigDialogComponent,
    LlmModelConfigDialogComponent,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectComponent,
    SelectItem,
    TranscriptionModelConfigDialogComponent,
    VoiceModelConfigDialogComponent,
} from '@shared/components';
import { SecretUsageResourceType } from '@shared/models';
import {
    EmbeddingConfigStorageService,
    LlmConfigStorageService,
    RealtimeConfigStorageService,
    SecretsApiService,
    TranscriptionConfigStorageService,
} from '@shared/services';
import { extractHttpErrorMessage } from '@shared/utils';
import { Observable } from 'rxjs';

import { LoadingState } from '../../../../core/enums/loading-state.enum';
import { McpToolDialogComponent } from '../../../../features/tools/components/mcp-tool-dialog/mcp-tool-dialog.component';
import { CustomToolsService } from '../../../../features/tools/services/custom-tools/custom-tools.service';
import { McpToolsService } from '../../../../features/tools/services/mcp-tools/mcp-tools.service';
import { ToastService } from '../../../../services/notifications';
import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';
import { CreateCustomToolDialogComponent } from '../../../../user-settings-page/tools/custom-tool-editor/create-custom-tool-dialog/create-custom-tool-dialog.component';
import { NODE_COLORS, NODE_ICONS } from '../../../../visual-programming/core/enums/node-config';
import { NodeType } from '../../../../visual-programming/core/enums/node-type';
import {
    SecretUsageFlowItem,
    SecretUsageFlowNode,
    SecretUsageResourceItem,
    SecretUsageSimpleCategory,
    SecretUsageSummary,
    toSecretUsageSummary,
} from '../../models/secret-usage.model';

export interface SecretUsageDialogData {
    secretId: number;
    secretName: string;
}

type NodeTypeFilter = NodeType | null;

const NODE_TYPE_FILTER_ITEMS: SelectItem<NodeTypeFilter>[] = [
    { name: 'All', value: null },
    { name: 'Python Node', value: NodeType.PYTHON },
    { name: 'Classification Decision Table', value: NodeType.CLASSIFICATION_TABLE },
    { name: 'Webhook Node', value: NodeType.WEBHOOK_TRIGGER },
    { name: 'Telegram Node', value: NodeType.TELEGRAM_TRIGGER },
];

const NODE_TYPE_LABELS = new Map<NodeType, string>(
    NODE_TYPE_FILTER_ITEMS.filter((item) => item.value !== null).map((item) => [item.value as NodeType, item.name])
);

const CONFIG_TYPE_LABELS = new Map<SecretUsageResourceType, string>([
    ['llm_config', 'LLM'],
    ['embedding_config', 'Embedding'],
    ['realtime_config', 'Voice'],
    ['realtime_transcription_config', 'Transcription'],
]);

@Component({
    selector: 'app-secret-usage-dialog',
    templateUrl: './secret-usage-dialog.component.html',
    styleUrls: ['./secret-usage-dialog.component.scss'],
    imports: [
        CommonModule,
        AppSvgIconComponent,
        AppIconComponent,
        SearchComponent,
        SelectComponent,
        LoadingSpinnerComponent,
        ButtonComponent,
    ],
    animations: [
        trigger('collapseExpand', [
            state('expanded', style({ height: '*', opacity: 1, overflow: 'hidden' })),
            state('collapsed', style({ height: '0', opacity: 0, overflow: 'hidden' })),
            transition('expanded <=> collapsed', animate('200ms ease')),
        ]),
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SecretUsageDialogComponent implements OnInit {
    private readonly dialogRef = inject(DialogRef<void>);
    private readonly data = inject<SecretUsageDialogData>(DIALOG_DATA);
    private readonly router = inject(Router);
    private readonly secretsApiService = inject(SecretsApiService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly dialog = inject(Dialog);
    private readonly toastService = inject(ToastService);
    private readonly llmConfigStorageService = inject(LlmConfigStorageService);
    private readonly embeddingConfigStorageService = inject(EmbeddingConfigStorageService);
    private readonly realtimeConfigStorageService = inject(RealtimeConfigStorageService);
    private readonly transcriptionConfigStorageService = inject(TranscriptionConfigStorageService);
    private readonly mcpToolsService = inject(McpToolsService);
    private readonly customToolsService = inject(CustomToolsService);

    public readonly secretName = this.data.secretName;
    public readonly nodeTypeFilterItems = NODE_TYPE_FILTER_ITEMS;

    public readonly status = signal<LoadingState>(LoadingState.LOADING);
    public readonly errorMessage = signal<string | null>(null);
    public readonly usage = signal<SecretUsageSummary | null>(null);

    public readonly expandedFlowName = signal<string | null>(null);
    public readonly nodeSearchTerm = signal<string>('');
    public readonly nodeTypeFilter = signal<NodeTypeFilter>(null);

    ngOnInit(): void {
        this.loadUsage();
    }

    public loadUsage(): void {
        this.status.set(LoadingState.LOADING);
        this.secretsApiService
            .getSecretUsage(this.data.secretId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (response) => {
                    this.usage.set(toSecretUsageSummary(response));
                    this.status.set(LoadingState.LOADED);
                },
                error: (err: HttpErrorResponse) => {
                    this.errorMessage.set(extractHttpErrorMessage(err));
                    this.status.set(LoadingState.ERROR);
                },
            });
    }

    public filteredNodes(flow: SecretUsageFlowItem): SecretUsageFlowNode[] {
        const term = this.nodeSearchTerm().toLowerCase().trim();
        const typeFilter = this.nodeTypeFilter();
        return flow.nodes.filter((node) => {
            const matchesTerm = !term || node.name.toLowerCase().includes(term);
            const matchesType = typeFilter === null || node.nodeType === typeFilter;
            return matchesTerm && matchesType;
        });
    }

    public toggleFlow(flowName: string): void {
        if (this.expandedFlowName() === flowName) {
            this.expandedFlowName.set(null);
            return;
        }
        this.expandedFlowName.set(flowName);
        this.nodeSearchTerm.set('');
        this.nodeTypeFilter.set(null);
    }

    public isFlowExpanded(flowName: string): boolean {
        return this.expandedFlowName() === flowName;
    }

    public onNodeTypeFilterChange(value: unknown): void {
        this.nodeTypeFilter.set(value as NodeTypeFilter);
    }

    public nodeIcon(nodeType: NodeType): string {
        return NODE_ICONS[nodeType];
    }

    public nodeColor(nodeType: NodeType): string {
        return NODE_COLORS[nodeType];
    }

    public nodeTypeLabel(nodeType: NodeType): string {
        return NODE_TYPE_LABELS.get(nodeType) ?? '';
    }

    public configTypeLabel(type: SecretUsageResourceType): string {
        return CONFIG_TYPE_LABELS.get(type) ?? '';
    }

    public scrollToCategory(key: string): void {
        document.getElementById(`secret-usage-category-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    public navigateToFlow(flow: SecretUsageFlowItem): void {
        const urlTree = this.router.createUrlTree(['/flows', flow.id]);
        window.open(this.router.serializeUrl(urlTree), '_blank');
    }

    public navigateToNamedItem(category: SecretUsageSimpleCategory, item: SecretUsageResourceItem): void {
        if (category.key === 'llm_configs') {
            this.navigateToLlmConfig(item);
        } else {
            this.navigateToTool(item);
        }
    }

    private notFound(name: string): void {
        this.toastService.error(`Couldn't find "${name}" — it may have been renamed or deleted.`);
    }

    private navigateToLlmConfig(item: SecretUsageResourceItem): void {
        const target = this.llmConfigTarget(item.type);
        if (!target) {
            this.notFound(item.name);
            return;
        }
        target
            .configs()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((configs) => {
                const match = configs.find((config) => config.custom_name === item.name);
                if (!match) {
                    this.notFound(item.name);
                    return;
                }
                this.dialog.open(target.dialog, {
                    height: '90vh',
                    width: '600px',
                    data: { configId: match.id },
                });
            });
    }

    private llmConfigTarget(
        type: SecretUsageResourceType
    ): { configs: () => Observable<{ id: number; custom_name: string }[]>; dialog: ComponentType<unknown> } | null {
        switch (type) {
            case 'llm_config':
                return {
                    configs: () => this.llmConfigStorageService.getAllConfigs(),
                    dialog: LlmModelConfigDialogComponent,
                };
            case 'embedding_config':
                return {
                    configs: () => this.embeddingConfigStorageService.getAllConfigs(),
                    dialog: EmbeddingModelConfigDialogComponent,
                };
            case 'realtime_config':
                return {
                    configs: () => this.realtimeConfigStorageService.getAllConfigs(),
                    dialog: VoiceModelConfigDialogComponent,
                };
            case 'realtime_transcription_config':
                return {
                    configs: () => this.transcriptionConfigStorageService.getAllConfigs(),
                    dialog: TranscriptionModelConfigDialogComponent,
                };
            default:
                return null;
        }
    }

    private navigateToTool(item: SecretUsageResourceItem): void {
        if (item.type === 'mcp_tool') {
            this.mcpToolsService
                .getMcpTools({ name: item.name })
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((mcpTools) => {
                    const match = mcpTools.find((tool) => tool.name === item.name);
                    if (!match) {
                        this.notFound(item.name);
                        return;
                    }
                    this.dialog.open(McpToolDialogComponent, {
                        data: { selectedTool: match },
                        maxWidth: '95vw',
                        maxHeight: '90vh',
                        autoFocus: true,
                    });
                });
            return;
        }
        this.customToolsService
            .getPythonCodeTools()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((customTools) => {
                const match = customTools.find((tool) => tool.name === item.name);
                if (!match) {
                    this.notFound(item.name);
                    return;
                }
                this.dialog.open(CreateCustomToolDialogComponent, {
                    data: { pythonTools: customTools, selectedTool: match },
                });
            });
    }

    public onClose(): void {
        this.dialogRef.close();
    }
}
