import { Clipboard, ClipboardModule } from '@angular/cdk/clipboard';
import { NgTemplateOutlet } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    inject,
    input,
    signal,
    TemplateRef,
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
import { ResourceCode, WebhookTriggerModel } from '@shared/models';
import { SecretsStorageService } from '@shared/services';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { WebhookTriggerNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { SidePanelService } from '../../../services/side-panel.service';
import { formatTestPayload } from '../../../utils/test-run';
import { NodeSecretsFieldComponent } from '../../node-secrets-field/node-secrets-field.component';
import { RunTestPayloadButtonComponent } from '../shared/run-test-payload-button/run-test-payload-button.component';
import { TestPayloadSectionComponent } from '../shared/test-payload-section/test-payload-section.component';
import { TriggerTestPayloadState, withTestPayload } from '../shared/test-payload-section/trigger-test-payload.state';

/** The editor shown in the big right-hand pane of the expanded panel; the other one moves to the left column. */
type WebhookExpandedPane = 'code' | 'payload';

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

    public override readonly isExpanded = input<boolean>(false);
    public readonly graphId = input<number | null>(null);

    /** Rendered by the panel shell in its header. */
    public readonly headerActionsTemplate = viewChild<TemplateRef<unknown>>('headerActionsTpl');

    public readonly isFormCollapsed = signal<boolean>(false);
    protected readonly expandedPane = signal<WebhookExpandedPane>('code');
    /** Height in px of an editor shown as a card (small panel, or the left column of the expanded one). */
    protected readonly smallEditorHeight = 220;
    protected readonly testPayload = new TriggerTestPayloadState(
        'webhook-trigger',
        computed(() => this.node().id)
    );
    protected readonly leftColumnWidth = createColumnWidthState('webhook-trigger-node', 406);

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
        return form;
    }

    createUpdatedNode(): WebhookTriggerNodeModel {
        const librariesArray = this.form.value.libraries
            ? this.form.value.libraries
                  .split(',')
                  .map((lib: string) => lib.trim())
                  .filter((lib: string) => lib.length > 0)
            : [];

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
                    libraries: librariesArray,
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

    copyWebhookUrl(): void {
        const url = this.fullUrl();
        if (!url) return;

        this.clipboard.copy(url);
        this.copied.set(true);
    }
}
