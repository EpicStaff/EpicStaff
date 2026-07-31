import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    effect,
    inject,
    input,
    signal,
    untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { Subject } from 'rxjs';
import { debounceTime, takeUntil } from 'rxjs/operators';

import { ImportExportService } from '../../../../core/services/import-export.service';
import { ToastService } from '../../../../services/notifications/toast.service';
import {
    ActionDropdownButtonComponent,
    ActionDropdownItem,
} from '../../../../shared/components/action-dropdown-button/action-dropdown-button.component';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ConfirmationDialogService } from '../../../../shared/components/cofirm-dialog/confimation-dialog.service';
import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { HelpTooltipComponent } from '../../../../shared/components/help-tooltip/help-tooltip.component';
import { LlmModelSelectorComponent } from '../../../../shared/components/llm-model-selector/llm-model-selector.component';
import { SelectComponent, SelectItem } from '../../../../shared/components/select/select.component';
import { FullLLMConfigService } from '../../../../shared/services/llms/full-llm-config.service';
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
import { LockableFieldComponent } from '../../lockable-field/lockable-field.component';
import { CdtExportImportService } from './cdt-export-import.service';
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
        HelpTooltipComponent,
        AppSvgIconComponent,
        ActionDropdownButtonComponent,
        SelectComponent,
        LockableFieldComponent,
    ],
    templateUrl: './classification-decision-table-node-panel.component.html',
    styleUrls: ['./classification-decision-table-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ClassificationDecisionTableNodePanelComponent extends BaseSidePanel<ClassificationDecisionTableNodeModel> {
    public override readonly isExpanded = input<boolean>(true);
    public readonly graphId = input<number | null>(null);

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
    private sanitizer = inject(DomSanitizer);

    public activeTab = signal<TabType>('table');
    private lastFormNodeId: string | null = null;

    public conditionGroups = signal<ConditionGroup[]>([]);
    public prompts = signal<Record<string, PromptConfig>>({});
    public readonly llmConfigs = this.fullLlmConfigService.fullLLMConfigs;
    public editingPromptId = signal<string | null>(null);
    public pendingPromptName = signal<string>('');
    public newPromptId = '';

    public preCode: string = '';
    public postCode: string = '';
    private readonly codeChange$ = new Subject<void>();
    private readonly reinitDestroy$ = new Subject<void>();
    private sidePanelService = inject(SidePanelService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly importExportService = inject(ImportExportService);
    private readonly cdtExportImportService = inject(CdtExportImportService);
    private readonly toastService = inject(ToastService);

    // Sub-FormGroups for InputMapComponent in pre/post tabs.
    public preInputForm!: FormGroup;
    public postInputForm!: FormGroup;

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
        const obj = state as Record<string, unknown>;
        const vars = obj['variables'];
        if (vars && typeof vars === 'object') {
            return Object.keys(vars as Record<string, unknown>);
        }
        return [];
    });

    public readonly llmConfigOptions = computed<{ id: number; label: string }[]>(() =>
        this.llmConfigs().map((c) => ({
            id: c.id,
            label: c.custom_name || `LLM #${c.id}`,
        }))
    );

    constructor() {
        super();
        effect(() => {
            const node = this.node();
            const nodePrompts = ((node?.data as { table?: ClassificationDecisionTableData })?.table?.prompts ??
                {}) as Record<string, PromptConfig>;
            const current = untracked(() => this.prompts());
            const updated = { ...current };
            let changed = false;
            for (const [key, cfg] of Object.entries(nodePrompts)) {
                const typedCfg = cfg as PromptConfig;
                if (typedCfg.backendId != null && (updated[key] as PromptConfig | undefined)?.backendId == null) {
                    updated[key] = { ...(updated[key] as PromptConfig), backendId: typedCfg.backendId };
                    changed = true;
                }
            }
            if (changed) this.prompts.set(updated);
        });
        this.codeChange$
            .pipe(debounceTime(300), takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.sidePanelService.triggerAutosave());
        this.fullLlmConfigService.getFullLLMConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    public availableNodeItems = computed<SelectItem[]>(() => {
        const nodes = this.flowService.nodes();
        const currentNodeId = this.node().id;

        const nodeItems = nodes
            .filter(
                (node) =>
                    node.type !== NodeType.NOTE &&
                    node.type !== NodeType.START &&
                    node.type !== NodeType.WEBHOOK_TRIGGER &&
                    node.type !== NodeType.TELEGRAM_TRIGGER &&
                    node.id !== currentNodeId
            )
            .map((node) => ({
                value: node.id,
                name: node.node_name || node.id,
            }));

        return [{ name: 'Select Node', value: '' }, ...nodeItems];
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
            code: tableData.pre_computation_code || '',
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

        const groupsCopy = this.cloneConditionGroups(tableData.condition_groups || []);
        this.conditionGroups.set(groupsCopy);
        this.prompts.set({ ...(tableData.prompts || {}) });

        // Only reset to the Table tab when a different node is opened — not on every remote
        // merge (initializeForm runs on each peer update), which would yank a viewing
        // collaborator back to the Table tab whenever the editor changes anything.
        if (this.lastFormNodeId !== node.id) {
            this.activeTab.set('table');
            this.lastFormNodeId = node.id;
        }

        return form;
    }

    // Runs exactly once per real reinit (a different node opened), never on the
    // per-node-update merge cycles that call initializeForm() again just to diff
    // values — see BaseSidePanel.mergeRemoteIntoForm. Sub-form instances and their
    // valueChanges subscriptions must be created here, not in initializeForm(),
    // or every remote/self node update would replace preInputForm/postInputForm
    // (disconnecting them from the canonical form) and pile up duplicate subscriptions.
    protected override onFormReinitialized(): void {
        this.reinitDestroy$.next();

        const form = this.form;

        // Build sub-forms for InputMapComponent.
        // InputMapComponent uses ControlContainer to find its parent FormGroup and then
        // looks up 'input_map' and 'test_input' arrays by name. By providing these sub-forms
        // via [formGroup] in the template, InputMapComponent finds the correct arrays.
        // 'test_input' is never persisted — it only exists to satisfy InputMapComponent.
        this.preInputForm = this.fb.group({
            input_map: this.fb.array([] as FormGroup[]),
            test_input: this.fb.array([] as FormGroup[]),
        });
        this.postInputForm = this.fb.group({
            input_map: this.fb.array([] as FormGroup[]),
            test_input: this.fb.array([] as FormGroup[]),
        });

        // Seed sub-form input_map arrays from the canonical arrays on the main form.
        this.seedSubFormInputMap(this.preInputForm, form.get('pre_input_map') as FormArray);
        this.seedSubFormInputMap(this.postInputForm, form.get('post_input_map') as FormArray);

        // Sync sub-form input_map → canonical array on main form whenever user edits.
        (this.preInputForm.get('input_map') as FormArray).valueChanges
            .pipe(takeUntil(this.reinitDestroy$), takeUntilDestroyed(this.destroyRef))
            .subscribe((pairs: { key: string; value: string }[]) => {
                this.syncSubFormToMainArray(form, 'pre_input_map', pairs);
                this.preInputMapVersion.update((v) => v + 1);
                this.codeChange$.next();
            });

        (this.postInputForm.get('input_map') as FormArray).valueChanges
            .pipe(takeUntil(this.reinitDestroy$), takeUntilDestroyed(this.destroyRef))
            .subscribe((pairs: { key: string; value: string }[]) => {
                this.syncSubFormToMainArray(form, 'post_input_map', pairs);
                this.codeChange$.next();
            });

        ['pre_output_variable_path', 'pre_libraries', 'post_output_variable_path', 'post_libraries'].forEach(
            (controlName) => {
                form.get(controlName)!
                    .valueChanges.pipe(takeUntil(this.reinitDestroy$), takeUntilDestroyed(this.destroyRef))
                    .subscribe(() => this.codeChange$.next());
            }
        );
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

        const updatedPorts = generatePortsForClassificationDecisionTableNode(currentNode.id, conditionGroups);

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
    }

    public onOpenPromptLibrary(event: { action: 'create' } | { action: 'edit'; promptId: string }): void {
        this.setActiveTab('prompts');
        if (event.action === 'create') {
            this.addPrompt();
        } else {
            this.editingPromptId.set(event.promptId);
            this.pendingPromptName.set(event.promptId);
        }
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
            result_variable: 'prompt_result',
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
        this.confirmationDialogService
            .confirm({
                title: 'Delete Prompt',
                message: `Are you sure you want to delete <strong>${id}</strong> prompt?`,
                confirmText: 'Delete',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .subscribe((result) => {
                if (result === true) {
                    this.performDeletePrompt(id);
                }
            });
    }

    private performDeletePrompt(id: string): void {
        const current = { ...this.prompts() };
        delete current[id];
        this.prompts.set(current);
        if (this.editingPromptId() === id) {
            this.editingPromptId.set(null);
        }
        this.sidePanelService.triggerAutosave();
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

    // ── Export ──

    readonly exportFormatItems: ActionDropdownItem[] = [
        { label: 'JSON', value: 'json' },
        { label: 'CSV', value: 'csv' },
    ];

    public onExportItemSelected(item: ActionDropdownItem): void {
        if (item.value === 'csv') {
            this.exportAsCsv();
        } else {
            this.exportAsJson();
        }
    }

    public exportAsJson(): void {
        const backendId = this.node().backendId;
        if (backendId == null) {
            this.toastService.warning('Save the flow before exporting', 3000, 'bottom-right');
            return;
        }
        this.importExportService
            .cdtExport(backendId, 'json')
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (blob) => this.downloadBlob(blob, this.buildFileName('json')),
                error: () => this.toastService.error('Export failed.'),
            });
    }

    public exportAsCsv(): void {
        if (this.node().backendId == null) {
            this.toastService.warning('Save the flow before exporting', 3000, 'bottom-right');
        }
        const exportData = this.cdtExportImportService.buildExportData({
            nodeName: this.form.value.node_name ?? '',
            preCode: this.preCode,
            preLibraries: this.parseLibraries(this.form.value.pre_libraries),
            preInputMap: this.serializeInputMap('pre_input_map'),
            preOutputVariablePath: this.form.value.pre_output_variable_path || null,
            postCode: this.postCode,
            postLibraries: this.parseLibraries(this.form.value.post_libraries),
            postInputMap: this.serializeInputMap('post_input_map'),
            postOutputVariablePath: this.form.value.post_output_variable_path || null,
            defaultLlmConfig: this.form.value.default_llm_config || null,
            conditionGroups: this.conditionGroups(),
            prompts: this.prompts(),
        });
        const csv = this.cdtExportImportService.exportToCsv(exportData);
        this.cdtExportImportService.downloadFile(csv, this.buildFileName('csv'), 'text/csv;charset=utf-8;');
    }

    private downloadBlob(blob: Blob, filename: string): void {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    private buildFileName(extension: string): string {
        const base = (this.form.value.node_name || 'classification-decision-table')
            .toString()
            .trim()
            .replace(/[^a-z0-9-_]+/gi, '-')
            .replace(/^-+|-+$/g, '')
            .toLowerCase();
        return `${base || 'cdt'}.${extension}`;
    }

    // ── Code editor handlers ──

    public onPreCodeChange(code: string): void {
        this.preCode = code;
        this.notifyExternalChange();
        this.codeChange$.next();
    }

    public onPostCodeChange(code: string): void {
        this.postCode = code;
        this.notifyExternalChange();
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

    /**
     * Copies entries from a canonical main-form FormArray into a sub-form's input_map array.
     * Called once during initializeForm to seed the sub-forms.
     */
    private seedSubFormInputMap(subForm: FormGroup, sourceArray: FormArray): void {
        const dest = subForm.get('input_map') as FormArray;
        dest.clear({ emitEvent: false });
        sourceArray.controls.forEach((ctrl) => {
            dest.push(
                this.fb.group({
                    key: [ctrl.value.key ?? ''],
                    value: [ctrl.value.value ?? ''],
                }),
                { emitEvent: false }
            );
        });
    }

    /**
     * Mirrors the sub-form's input_map value back into the canonical FormArray on the main form.
     * Called inside sub-form valueChanges subscriptions so serialization always reads up-to-date data.
     */
    private syncSubFormToMainArray(form: FormGroup, arrayName: string, pairs: { key: string; value: string }[]): void {
        const canonical = form.get(arrayName) as FormArray;
        canonical.clear({ emitEvent: false });
        pairs.forEach((pair) => {
            canonical.push(
                this.fb.group({
                    key: [pair.key ?? ''],
                    value: [pair.value ?? ''],
                }),
                { emitEvent: false }
            );
        });
        canonical.markAsDirty();
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
            pre_computation_code: '',
            condition_groups: [],
            prompts: {},
            output_variables: [],
            route_variable_name: 'route_code',
            default_next_node: null,
            next_error_node: null,
        };
    }
}
