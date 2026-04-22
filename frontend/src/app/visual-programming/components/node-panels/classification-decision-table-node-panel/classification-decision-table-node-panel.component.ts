import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    DestroyRef,
    inject,
    input,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { Subject } from 'rxjs';
import { debounceTime } from 'rxjs/operators';

import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { LlmModelSelectorComponent } from '../../../../shared/components/llm-model-selector/llm-model-selector.component';
import { FullLLMConfig, FullLLMConfigService } from '../../../../shared/services/llms/full-llm-config.service';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { NodeType } from '../../../core/enums/node-type';
import { generatePortsForClassificationDecisionTableNode } from '../../../core/helpers/helpers';
import {
    ClassificationDecisionTableData,
    PromptConfig,
} from '../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../core/models/decision-table.model';
import { ClassificationDecisionTableNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { FlowService } from '../../../services/flow.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { InputMapComponent } from '../../input-map/input-map.component';
import { ClassificationDecisionTableGridComponent } from './classification-decision-table-grid/classification-decision-table-grid.component';

type TabType = 'table' | 'precomputation' | 'postcomputation' | 'prompts';

@Component({
    selector: 'app-classification-decision-table-node-panel',
    imports: [
        ReactiveFormsModule,
        FormsModule,
        CustomInputComponent,
        CommonModule,
        ClassificationDecisionTableGridComponent,
        LlmModelSelectorComponent,
        InputMapComponent,
        CodeEditorComponent,
    ],
    templateUrl: './classification-decision-table-node-panel.component.html',
    styleUrls: ['./classification-decision-table-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ClassificationDecisionTableNodePanelComponent extends BaseSidePanel<ClassificationDecisionTableNodeModel> {
    public override readonly isExpanded = input<boolean>(true);

    private flowService = inject(FlowService);

    // Extract graph ID once at construction — URL is /flows/:id and doesn't change while panel is open
    private readonly graphIdFromUrl = (() => {
        const match = window.location.pathname.match(/\/flows\/(\d+)/);
        return match?.[1] ?? '0';
    })();

    // Stable storage key: graphId + nodeNumber (nodeNumber is in metadata, survives save/delete cycles)
    readonly gridStorageId = computed(() => {
        const nodeNum = this.node().nodeNumber ?? this.node().backendId ?? 0;
        return `${this.graphIdFromUrl}_${nodeNum}`;
    });
    private cdr = inject(ChangeDetectorRef);
    private fullLlmConfigService = inject(FullLLMConfigService);
    private destroyRef = inject(DestroyRef);
    private sanitizer = inject(DomSanitizer);

    public activeTab = signal<TabType>('table');

    private get tabStorageKey(): string {
        return `cdt-panel-tab-${this.node().id}`;
    }
    public conditionGroups = signal<ConditionGroup[]>([]);
    public prompts = signal<Record<string, PromptConfig>>({});
    public llmConfigs: FullLLMConfig[] = [];
    public editingPromptId = signal<string | null>(null);
    public pendingPromptName = signal<string>('');
    public newPromptId = '';

    public preCode: string = '';
    public postCode: string = '';
    private readonly codeChange$ = new Subject<void>();
    private sidePanelService = inject(SidePanelService);

    public promptEntries = computed(() => {
        const p = this.prompts();
        return Object.entries(p).map(([id, config]) => ({ id, ...config }));
    });

    private preInputMapVersion = signal(0);

    public preInputMapKeys = computed(() => {
        this.preInputMapVersion();
        if (!this.form) return [];
        const arr = this.form.get('pre_input_map') as FormArray;
        if (!arr) return [];
        return arr.controls.map((ctrl) => ctrl.value?.key?.trim()).filter((k: string) => !!k);
    });

    public inputMapVariableNames = computed(() => {
        this.preInputMapVersion();
        if (!this.form) return [];
        const arr = this.form.get('pre_input_map') as FormArray;
        if (!arr) return [];
        return arr.controls
            .map((ctrl) => {
                const val = (ctrl.value?.value || '').trim();
                if (val.startsWith('variables.')) {
                    return val.substring('variables.'.length);
                }
                return null;
            })
            .filter((k: string | null): k is string => !!k);
    });

    public domainKeys = computed(() => {
        const state = this.flowService.startNodeInitialState();
        if (!state || typeof state !== 'object') return [];
        return Object.keys(state);
    });

    public get llmConfigOptions(): { id: number; label: string }[] {
        return this.llmConfigs.map((c) => ({
            id: c.id,
            label: c.custom_name || `LLM #${c.id}`,
        }));
    }

    constructor() {
        super();
        this.codeChange$
            .pipe(debounceTime(300), takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.sidePanelService.triggerAutosave());
        this.fullLlmConfigService
            .getFullLLMConfigs()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (configs) => {
                    this.llmConfigs = configs;
                    this.cdr.markForCheck();
                },
                error: () => {
                    this.llmConfigs = [];
                    this.cdr.markForCheck();
                },
            });
    }

    public availableNodes = computed(() => {
        const nodes = this.flowService.nodes();

        return nodes
            .filter(
                (node) =>
                    node.type !== NodeType.NOTE &&
                    node.type !== NodeType.START &&
                    node.type !== NodeType.WEBHOOK_TRIGGER &&
                    node.type !== NodeType.TELEGRAM_TRIGGER
            )
            .map((node) => ({
                value: node.id,
                label: node.node_name || node.id,
            }));
    });

    get activeColor(): string {
        return this.node().color || '#685fff';
    }

    protected initializeForm(): FormGroup {
        const node = this.node();
        const tableData: ClassificationDecisionTableData =
            (node.data as { table?: ClassificationDecisionTableData }).table ?? this.getDefaultTableData();
        const nodes = this.flowService.nodes();
        const connections = this.flowService.connections();

        const findNodeId = (value: string | null, role: 'default' | 'error'): string => {
            if (value) {
                const foundNode = nodes.find((n) => n.id === value || n.node_name === value);
                if (foundNode) {
                    return foundNode.id;
                }
            }

            const portSuffix = role === 'default' ? 'decision-default' : 'decision-error';
            const portId = `${node.id}_${portSuffix}`;

            const connection = connections.find((c) => c.sourceNodeId === node.id && c.sourcePortId === portId);

            if (connection) {
                return connection.targetNodeId;
            }

            return value || '';
        };

        const defaultNext = findNodeId(tableData.default_next_node, 'default');
        const errorNext = findNodeId(tableData.next_error_node, 'error');

        const preComp = tableData.pre_computation || {
            code: tableData.pre_computation_code || this.getDefaultPreComputation(),
            input_map: tableData.pre_input_map || {},
            output_variable_path: tableData.pre_output_variable_path,
        };
        const postComp = tableData.post_computation || {
            code: tableData.post_computation_code || '',
            input_map: tableData.post_input_map || {},
            output_variable_path: tableData.post_output_variable_path,
        };

        this.preCode = preComp.code || '';
        this.postCode = postComp.code || '';

        const form = this.fb.group({
            node_name: [node.node_name, this.createNodeNameValidators()],
            pre_computation_code: [this.preCode],
            pre_input_map: this.fb.array([] as FormGroup[]),
            pre_output_variable_path: [preComp.output_variable_path || ''],
            pre_libraries: [preComp.libraries?.join(', ') || ''],
            post_computation_code: [this.postCode],
            post_input_map: this.fb.array([] as FormGroup[]),
            post_output_variable_path: [postComp.output_variable_path || ''],
            post_libraries: [postComp.libraries?.join(', ') || ''],
            default_next_node: [defaultNext],
            next_error_node: [errorNext],
            default_llm_config: [tableData.default_llm_config || null],
        });

        this.initializeInputMapArray(form, 'pre_input_map', preComp.input_map || {});
        this.initializeInputMapArray(form, 'post_input_map', postComp.input_map || {});

        (form.get('pre_input_map') as FormArray).valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => {
                this.preInputMapVersion.update((v) => v + 1);
                this.codeChange$.next();
            });

        (form.get('post_input_map') as FormArray).valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => {
                this.codeChange$.next();
            });

        ['pre_output_variable_path', 'pre_libraries', 'post_output_variable_path', 'post_libraries'].forEach(
            (controlName) => {
                form.get(controlName)!
                    .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe(() => this.codeChange$.next());
            }
        );

        const groupsCopy = this.cloneConditionGroups(tableData.condition_groups || []);
        this.conditionGroups.set(groupsCopy);
        this.prompts.set({ ...(tableData.prompts || {}) });

        // Restore persisted tab for this node, defaulting to 'table'
        const persistedTab = localStorage.getItem(this.tabStorageKey) as TabType | null;
        const validTabs: TabType[] = ['table', 'precomputation', 'postcomputation', 'prompts'];
        this.activeTab.set(persistedTab && validTabs.includes(persistedTab) ? persistedTab : 'table');

        return form;
    }

    createUpdatedNode(): ClassificationDecisionTableNodeModel {
        const currentNode = this.node();
        const conditionGroups = this.cloneConditionGroups(this.conditionGroups() || []);

        const preInputMap = this.serializeInputMap('pre_input_map');
        const postInputMap = this.serializeInputMap('post_input_map');

        const tableData: ClassificationDecisionTableData = {
            pre_computation_code: this.preCode,
            post_computation_code: this.postCode,
            pre_computation: {
                code: this.preCode,
                input_map: preInputMap,
                output_variable_path: this.form.value.pre_output_variable_path || undefined,
                libraries: this.parseLibraries(this.form.value.pre_libraries),
            },
            post_computation: {
                code: this.postCode,
                input_map: postInputMap,
                output_variable_path: this.form.value.post_output_variable_path || undefined,
                libraries: this.parseLibraries(this.form.value.post_libraries),
            },
            condition_groups: conditionGroups,
            route_variable_name: 'route_code',
            default_next_node: this.form.value.default_next_node,
            next_error_node: this.form.value.next_error_node,
            default_llm_config: this.form.value.default_llm_config || null,
            prompts: { ...this.prompts() },
        };

        // Calculate node size based on unique route codes with dock_visible=true
        const uniqueRouteCodes = new Set<string>();
        conditionGroups
            .filter((g) => g.route_code && g.dock_visible)
            .forEach((g) => uniqueRouteCodes.add(g.route_code!));

        const headerHeight = 60;
        const rowHeight = 46;
        const routeCodeCount = uniqueRouteCodes.size;
        const hasDefaultRow = 1;
        const hasErrorRow = 1;
        const totalRows = Math.max(routeCodeCount + hasDefaultRow + hasErrorRow, 2);
        const calculatedHeight = headerHeight + rowHeight * totalRows;

        const updatedSize = {
            width: currentNode.size?.width || 330,
            height: Math.max(calculatedHeight, 152),
        };

        const updatedPorts = generatePortsForClassificationDecisionTableNode(
            currentNode.id,
            conditionGroups,
            !!tableData.default_next_node,
            !!tableData.next_error_node
        );

        return {
            ...currentNode,
            node_name: this.form.value.node_name,
            size: updatedSize,
            ports: updatedPorts,
            data: {
                name: this.form.value.node_name || 'Classification Decision Table',
                table: tableData,
            },
        };
    }

    public setActiveTab(tab: TabType): void {
        this.activeTab.set(tab);
        localStorage.setItem(this.tabStorageKey, tab);
    }

    public onConditionGroupsChange(groups: ConditionGroup[]): void {
        this.conditionGroups.set(this.cloneConditionGroups(groups));
        this.cdr.markForCheck();
        this.sidePanelService.triggerAutosave();
    }

    // ── Prompt Library ──

    public addPrompt(): void {
        const existing = this.prompts();
        let n = 1;
        while (existing[`prompt_${n}`]) n++;
        const newId = `prompt_${n}`;
        const newConfig: PromptConfig = {
            prompt_text: '',
            llm_config: null,
            output_schema: null,
            result_variable: '',
            variable_mappings: {},
        };
        this.prompts.update((p) => ({ ...p, [newId]: newConfig }));
        this.editingPromptId.set(newId);
        this.pendingPromptName.set(newId);
        this.sidePanelService.triggerAutosave();
    }

    public renamePrompt(oldId: string, newId: string): void {
        if (!newId.trim() || newId === oldId) return;
        const trimmed = newId.trim();
        const current = this.prompts();
        if (current[trimmed]) return; // already exists, don't overwrite
        const config = current[oldId];
        if (!config) return;
        const updated: Record<string, PromptConfig> = {};
        Object.entries(current).forEach(([k, v]) => {
            updated[k === oldId ? trimmed : k] = v;
        });
        this.prompts.set(updated);
        this.editingPromptId.set(trimmed);
        this.sidePanelService.triggerAutosave();
    }

    public onPromptAdd(id: string, config: PromptConfig): void {
        const current = this.prompts();
        if (current[id]) return; // duplicate
        this.prompts.set({ ...current, [id]: config });
    }

    public updatePrompt(id: string, field: keyof PromptConfig, value: PromptConfig[keyof PromptConfig]): void {
        const current = { ...this.prompts() };
        if (!current[id]) return;
        current[id] = { ...current[id], [field]: value };
        this.prompts.set(current);
        this.sidePanelService.triggerAutosave();
    }

    public deletePrompt(id: string): void {
        const current = { ...this.prompts() };
        delete current[id];
        this.prompts.set(current);
        this.sidePanelService.triggerAutosave();
        if (this.editingPromptId() === id) {
            this.editingPromptId.set(null);
        }
    }

    public toggleEditPrompt(id: string): void {
        const newId = this.editingPromptId() === id ? null : id;
        this.editingPromptId.set(newId);
        if (newId) {
            this.pendingPromptName.set(newId);
        }
    }

    public commitPromptRename(oldId: string): void {
        const newName = this.pendingPromptName().trim();
        if (newName && newName !== oldId) {
            this.renamePrompt(oldId, newName);
        }
    }

    public onPromptLlmChange(promptId: string, llmId: number | string | null): void {
        const parsed = llmId === '' || llmId == null ? null : Number(llmId);
        const finalValue = Number.isFinite(parsed) ? parsed : null;
        this.updatePrompt(promptId, 'llm_config', finalValue);
    }

    public getLlmIdAsNumber(llmConfig: number | null): number | null {
        return llmConfig ?? null;
    }

    public getSchemaString(schema: PromptConfig['output_schema']): string {
        if (!schema || (typeof schema === 'object' && Object.keys(schema).length === 0)) {
            return '';
        }
        if (typeof schema === 'string') {
            return schema;
        }
        return JSON.stringify(schema, null, 2);
    }

    public onSchemaChange(promptId: string, value: string): void {
        try {
            const parsed = JSON.parse(value);
            this.updatePrompt(promptId, 'output_schema', parsed);
        } catch {
            // Store as string if not valid JSON yet (user still typing)
            this.updatePrompt(promptId, 'output_schema', value);
        }
    }

    public onPromptTextChange(promptId: string, value: string): void {
        this.updatePrompt(promptId, 'prompt_text', value);
    }

    public getHighlightedPromptText(text: string): SafeHtml {
        if (!text) {
            return this.sanitizer.bypassSecurityTrustHtml('');
        }
        const escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const highlighted = escaped.replace(/\{[^}]+\}/g, (match) => `<span class="var-token">${match}</span>`);
        return this.sanitizer.bypassSecurityTrustHtml(highlighted);
    }

    // ── Code editor handlers ──

    public onPreCodeChange(code: string): void {
        this.preCode = code;
        this.codeChange$.next();
    }

    public onPostCodeChange(code: string): void {
        this.postCode = code;
        this.codeChange$.next();
    }

    // ── Input map helpers ──

    private parseLibraries(value: string | null | undefined): string[] {
        if (!value) return [];
        return value
            .split(',')
            .map((lib: string) => lib.trim())
            .filter((lib: string) => lib.length > 0);
    }

    private initializeInputMapArray(form: FormGroup, arrayName: string, map: Record<string, string>): void {
        const arr = form.get(arrayName) as FormArray;
        const entries = Object.entries(map);
        if (entries.length > 0) {
            entries.forEach(([key, value]) => {
                arr.push(
                    this.fb.group({
                        key: [key],
                        value: [value],
                    }),
                    { emitEvent: false }
                );
            });
        } else {
            arr.push(
                this.fb.group({
                    key: [''],
                    value: ['variables.'],
                }),
                { emitEvent: false }
            );
        }
    }

    private serializeInputMap(arrayName: string): Record<string, string> {
        const arr = this.form.get(arrayName) as FormArray;
        const result: Record<string, string> = {};
        arr.controls.forEach((ctrl) => {
            const pair = ctrl.value;
            if (pair.key?.trim()) {
                result[pair.key.trim()] = pair.value || '';
            }
        });
        return result;
    }

    private cloneConditionGroups(groups: ConditionGroup[]): ConditionGroup[] {
        return groups.map((group) => ({
            ...group,
            conditions: (group.conditions || []).map((condition) => ({
                ...condition,
            })),
        }));
    }

    private getDefaultTableData(): ClassificationDecisionTableData {
        return {
            pre_computation_code: this.getDefaultPreComputation(),
            condition_groups: [],
            prompts: {},
            output_variables: [],
            route_variable_name: 'route_code',
            default_next_node: null,
            next_error_node: null,
        };
    }

    private getDefaultPreComputation(): string {
        return `def main(arg1: str, arg2: str) -> dict:
    return {
        "result": arg1 + arg2,
    }
`;
    }
}
