import { Clipboard, ClipboardModule } from '@angular/cdk/clipboard';
import { NgTemplateOutlet } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    inject,
    input,
    signal,
    TemplateRef,
    untracked,
    viewChild,
} from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import {
    ColumnResizeDividerComponent,
    createColumnWidthState,
    CustomInputComponent,
    ValidationErrorsComponent,
    WebhookTriggerSelectComponent,
} from '@shared/components';
import { GetPythonCodeRequest, ResourceCode, toSecretIds, WebhookTriggerModel } from '@shared/models';
import { SecretsStorageService } from '@shared/services';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { WebhookTriggerNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { FlowService } from '../../../services/flow.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { describeTestRunBlocker, formatTestPayload } from '../../../utils/test-run';
import { NodeSecretsFieldComponent } from '../../node-secrets-field/node-secrets-field.component';
import { parseCommaSeparatedList } from '../node-panel-form.utils';
import { PythonTerminalComponent } from '../python-node-panel/python-terminal/python-terminal.component';
import { PythonCodeTestRun } from '../shared/python-code-test-run/python-code-test-run';
import {
    PYTHON_CODE_RUNNING_MESSAGE,
    pythonCodeSignature,
    resolveStoredCodeState,
    SAVE_GRAPH_BEFORE_CODE_RUN_MESSAGE,
    SAVE_NODE_BEFORE_CODE_RUN_MESSAGE,
    SAVE_TO_RUN_LATEST_CODE_MESSAGE,
    STORED_GRAPH_OUTDATED_MESSAGE,
    StoredCodeState,
} from '../shared/python-code-test-run/stored-python-code';
import { RunTestPayloadButtonComponent } from '../shared/run-test-payload-button/run-test-payload-button.component';
import { TestPayloadSectionComponent } from '../shared/test-payload-section/test-payload-section.component';
import { TriggerTestPayloadState, withTestPayload } from '../shared/test-payload-section/trigger-test-payload.state';

/** The editor shown in the big right-hand pane of the expanded panel; the other one moves to the left column. */
type WebhookExpandedPane = 'code' | 'payload';

export const RUN_PYTHON_CODE_LABEL = 'Run python code';

@Component({
    selector: 'app-webhook-trigger-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        CodeEditorComponent,
        ClipboardModule,
        NodeSecretsFieldComponent,
        WebhookTriggerSelectComponent,
        ColumnResizeDividerComponent,
        ValidationErrorsComponent,
        TestPayloadSectionComponent,
        RunTestPayloadButtonComponent,
        PythonTerminalComponent,
        NgTemplateOutlet,
    ],
    templateUrl: 'webhook-trigger-node-panel.component.html',
    styleUrls: ['webhook-trigger-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WebhookTriggerNodePanelComponent extends BaseSidePanel<WebhookTriggerNodeModel> {
    private readonly clipboard = inject(Clipboard);
    private readonly secretsStorageService = inject(SecretsStorageService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly sidePanelService = inject(SidePanelService);
    private readonly flowService = inject(FlowService);

    public override readonly isExpanded = input<boolean>(false);
    public readonly graphId = input<number | null>(null);

    /** Rendered by the panel shell in its header. */
    public readonly headerActionsTemplate = viewChild<TemplateRef<unknown>>('headerActionsTpl');

    public readonly isFormCollapsed = signal<boolean>(false);
    protected readonly expandedPane = signal<WebhookExpandedPane>('code');
    /** Set by the first run: the terminal then stays under the code (it has its own hide toggle). */
    private readonly isCodeTerminalShown = signal(false);
    /** Height in px of an editor shown as a card (small panel, or the left column of the expanded one). */
    protected readonly smallEditorHeight = 220;
    protected readonly testPayload = new TriggerTestPayloadState(
        'webhook-trigger',
        computed(() => this.node().id)
    );
    protected readonly leftColumnWidth = createColumnWidthState('webhook-trigger-node', 406);
    /** "Run python code": the stored code run alone with the test payload, shown in a terminal under the code. */
    protected readonly codeTestRun = new PythonCodeTestRun();
    protected readonly showCodeTerminal = computed(
        () => this.isCodeTerminalShown() && !this.isReadOnly() && this.isExpanded()
    );
    /**
     * Only in the expanded panel, where the output terminal has room. Hidden for a viewer and in a version
     * preview: running stored code needs Flows:Update.
     */
    protected readonly runPythonCodeIcon = computed(() =>
        this.isReadOnly() || !this.isExpanded() ? null : 'play-outline'
    );
    protected readonly runPythonCodeLabel = RUN_PYTHON_CODE_LABEL;
    /**
     * The code the backend has stored for this node, which is what run-python-code executes; null until the
     * node is in the saved graph (new, pasted, or deleted and restored).
     */
    private readonly savedPythonCode = computed<GetPythonCodeRequest | null>(() =>
        this.flowService.savedWebhookPythonCode(this.node().backendId)
    );
    private readonly storedCodeState = computed<StoredCodeState>(() =>
        resolveStoredCodeState(
            this.flowService.hasSavedGraph(),
            this.node().backendId,
            this.savedPythonCode(),
            (savedCode) => this.differsFromSaved(savedCode)
        )
    );
    /** Why "Run python code" cannot run now, or null. It runs the code saved on the backend, not the editor's. */
    protected readonly runCodeBlocker = computed<string | null>(() => {
        if (this.codeTestRun.isRunning()) return PYTHON_CODE_RUNNING_MESSAGE;
        switch (this.storedCodeState()) {
            case 'outdated':
                return STORED_GRAPH_OUTDATED_MESSAGE;
            case 'not-created':
                return SAVE_NODE_BEFORE_CODE_RUN_MESSAGE;
            case 'missing':
                return SAVE_GRAPH_BEFORE_CODE_RUN_MESSAGE;
            case 'changed':
                return SAVE_TO_RUN_LATEST_CODE_MESSAGE;
            case 'stored':
                // Only the payload: the lock while a flow run starts does not concern a code-only run.
                return describeTestRunBlocker(this.testPayload.check(), false);
        }
    });
    /** This node is being saved to the backend by the shell's Save (`onSaveClick`). */
    public readonly isSaving = computed(() => this.sidePanelService.savingNodeId() === this.node().id);
    /**
     * The node must be saved before its code can run although the panel may have no edit (e.g. a new node):
     * the panel shell then shows its Save button too. Save cannot help a `missing` or `outdated` node.
     */
    public readonly needsSave = computed(() => {
        if (this.isReadOnly()) return false;
        const state = this.storedCodeState();
        return state === 'not-created' || state === 'changed';
    });

    pythonCode: string = '';
    initialPythonCode: string = '';
    codeEditorHasError: boolean = false;
    /** Changing the selection needs Secrets:Use and an editable flow (not a Viewer, not a version preview). */
    public readonly canEditSecrets = computed(
        () => !this.isReadOnly() && this.permissionsService.canEditSecrets(ResourceCode.Flows)
    );
    public readonly secretsTooltip = computed(() =>
        this.canEditSecrets()
            ? "Secrets this webhook's code can access at runtime — create and manage secrets under Settings → Secrets. Press Ctrl+Space in the code editor to insert get_secret('name')."
            : this.isReadOnly()
              ? "Secrets assigned to this webhook's code."
              : "Secrets already assigned to this webhook's code. You don't have permission to change which secrets are selected."
    );
    public readonly selectedSecretIds = signal<number[]>([]);
    public readonly secretNames = computed(() =>
        this.canEditSecrets()
            ? this.secretsStorageService.namesForIds(this.selectedSecretIds())
            : (this.node().data.python_code.secret_names ?? [])
    );

    copied = signal<boolean>(false);
    selectedTrigger = signal<WebhookTriggerModel | null>(null);
    fullUrl = computed<string | null>(() => this.selectedTrigger()?.live_url ?? null);
    webhookInvalid = computed<boolean>(() => {
        const t = this.selectedTrigger();
        return !!t && !t.live_url;
    });

    constructor() {
        super();
        // A save gives a new node its backend id (a single-node save or a graph save); that is not an edit, so
        // it must not make the panel dirty and bring the Save button back.
        effect(() => {
            const backendId = this.node().backendId;
            untracked(() => {
                if (!this.form || this.baselineNode().backendId === backendId) return;
                this.updateBaseline((baseline) => ({ ...baseline, backendId }));
            });
        });
    }

    onTriggerResolved(trigger: WebhookTriggerModel | null): void {
        this.selectedTrigger.set(trigger);
    }

    // Fixed to the accent purple regardless of the node's own (green) identity color --
    // this panel's field highlights aren't meant to track the node's canvas color.
    get activeColor(): string {
        return 'var(--accent-color)';
    }

    onPythonCodeChange(code: string): void {
        this.pythonCode = code;
        this.notifyExternalChange();
    }

    onCodeErrorChange(hasError: boolean): void {
        this.codeEditorHasError = hasError;
    }

    onSecretsChange(values: number[]): void {
        this.selectedSecretIds.set(values);
        this.notifyExternalChange();
    }

    /** Runs the stored code alone, as a webhook delivery of the test payload would call it. */
    protected runPythonCode(): void {
        const payload = this.testPayload.check().payload;
        const backendId = this.node().backendId;
        if (this.runCodeBlocker() !== null || payload === null || backendId == null) return;
        this.isCodeTerminalShown.set(true);
        // The backend runs the code it stores for the node; the blocker ensures the panel's code matches it.
        this.codeTestRun.run({
            target: { type: 'webhook_trigger_node', id: backendId },
            variables: { trigger_payload: payload },
        });
    }

    protected onTestPayloadTextChange(text: string): void {
        this.testPayload.edit(text);
        this.notifyExternalChange();
    }

    /**
     * Puts `pane` in the big pane, expanding the panel first when it is small. The expand icon of the
     * pane already shown big passes the other pane, so it swaps them back (as in the task panel).
     */
    protected expandPane(pane: WebhookExpandedPane): void {
        this.expandedPane.set(pane);
        if (!this.isExpanded()) {
            this.sidePanelService.requestExpand();
        }
    }

    initializeForm(): FormGroup {
        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            libraries: [this.node().data.python_code.libraries?.join(', ') || ''],
            webhook_trigger: [this.node().data.webhook_trigger ?? null],
        });
        this.pythonCode = this.node().data.python_code.code || '';
        this.initialPythonCode = this.pythonCode;
        this.selectedSecretIds.set(this.node().data.python_code.secret_ids ?? []);
        this.testPayload.reset(formatTestPayload(this.node().data.test_payload ?? {}));
        // The panel is reused when another webhook node is selected: a run of the previous one stops, and
        // the terminal starts hidden and empty.
        this.codeTestRun.reset();
        this.isCodeTerminalShown.set(false);
        return form;
    }

    createUpdatedNode(): WebhookTriggerNodeModel {
        return {
            ...this.node(),
            node_name: this.form.value.node_name,
            input_map: {},
            output_variable_path: null,
            data: {
                ...this.node().data,
                webhook_trigger: this.form.value.webhook_trigger ?? null,
                python_code: {
                    name: this.node().data.python_code.name || 'Python Code',
                    code: this.pythonCode,
                    entrypoint: 'main',
                    libraries: this.libraries(),
                    secret_ids: this.selectedSecretIds(),
                    secret_names: this.secretNames(),
                },
                test_payload: this.testPayload.payloadToSave(this.node().data.test_payload),
            },
        };
    }

    /** An invalid test payload edit was left out of the saved node (on close, autosave or Ctrl+S), so say so. */
    protected override afterNodeSaved(): void {
        this.testPayload.reportInvalidEditNotSaved();
    }

    /**
     * On close / autosave the payload does not depend on the other fields: an edit of it is saved
     * alone, the rest stays unsaved.
     */
    protected override saveWhenFormInvalid(): WebhookTriggerNodeModel | null {
        const payload = this.testPayload.editToSaveAlone(this.baselineNode().data.test_payload);
        if (payload === null) return null;
        this.updateBaseline((baseline) => withTestPayload(baseline, payload));
        this.testPayload.reportSavedAlone(this.isDirty());
        return withTestPayload(this.node(), payload);
    }

    protected override hasUnsavedEditsOutsideNode(): boolean {
        return this.testPayload.hasUnsavedInvalidEdit();
    }

    /**
     * The shell's Save: saves this node to the backend now (as the Python node's Save does), so its code can
     * run. Like Ctrl+S it saves nothing while the form is invalid (the shell disables the button then) and
     * keeps every edit; an invalid test payload edit is left out and reported, as on close.
     */
    public onSaveClick(): void {
        if (this.isReadOnly() || this.isSaving() || !this.form) return;
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }
        const updatedNode = this.onSaveSilently();
        if (updatedNode) {
            this.sidePanelService.requestSaveNode(updatedNode);
        }
    }

    copyWebhookUrl(): void {
        const url = this.fullUrl();
        if (!url) return;

        this.clipboard.copy(url);
        this.copied.set(true);
    }

    /** The code, libraries or secrets in the panel are not the ones the backend has stored. */
    private differsFromSaved(savedCode: GetPythonCodeRequest): boolean {
        this.dirtyCheckTick();
        if (!this.form) return true;
        const saved = pythonCodeSignature(savedCode.code, savedCode.libraries, toSecretIds(savedCode.secrets));
        return saved !== pythonCodeSignature(this.pythonCode, this.libraries(), this.selectedSecretIds());
    }

    private libraries(): string[] {
        return parseCommaSeparatedList(this.form.value.libraries);
    }
}
