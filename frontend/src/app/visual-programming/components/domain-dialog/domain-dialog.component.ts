import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Overlay, OverlayModule, OverlayRef } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import { CommonModule } from '@angular/common';
import {
    Component,
    computed,
    DestroyRef,
    Inject,
    inject,
    OnDestroy,
    signal,
    ViewContainerRef,
    ViewEncapsulation,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    conformValuesToSample,
    type Diagnostic,
    type GenerateResult,
    type JsonObject,
    type JsonValue,
    mergeJsonIntoDdl,
    type SyncEntryKind,
    type SyncReport,
    type SyncReportEntry,
} from '@shared/ddl';
import { findNodeAtOffset, Node as JsonNode, parse as parseJsonc, parseTree } from 'jsonc-parser';

import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';
import { DdlEditorComponent } from '../../../shared/components/ddl-editor/ddl-editor.component';
import { JsonEditorComponent } from '../../../shared/components/json-editor/json-editor.component';
import {
    EMPTY_VALIDATION_RESULT,
    extractPathsFromArray,
    formatValidationMessages,
    hasValidationErrors,
    type PersistentVariablesValidationResult,
    validatePersistentVariables,
} from '../../services/persistent-variables.validator';
import {
    AutocompleteItem,
    AutocompleteOverlayComponent,
} from '../node-panels/decision-table-node-panel/decision-table-grid/cell-editors/expression-editor/autocomplete-overlay/autocomplete-overlay.component';

declare const monaco: typeof import('monaco-editor');

export interface DomainDialogData {
    initialData: Record<string, unknown>;
    ddlSource: string | null;
}

export interface DomainDialogResult {
    initialState: Record<string, unknown>;
    ddlSource: string | null;
}

export const DEFAULT_INITIAL_STATE: Record<string, unknown> = {
    variables: {
        context: null,
    },
    persistent_variables: {
        user: [],
        organization: [],
    },
};

type DomainDialogTab = 'schema' | 'json';
type DdlSyncStatus = 'never' | 'in-sync' | 'stale';

/** Debounce between the pane's last keystroke and the additive JSON→DDL merge. */
const PANE_MERGE_DEBOUNCE_MS = 300;

/** A pane edit newer than this is considered "in progress" — a DDL-driven reconcile defers to the pending merge instead. */
const RECENT_PANE_EDIT_THRESHOLD_MS = 1000;

function isPlainJsonObject(value: unknown): value is JsonObject {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Parses `text` and re-serializes it with no whitespace so structurally-equal-but-differently-formatted JSON compares equal. */
function canonicalizeJson(text: string): string | null {
    try {
        return JSON.stringify(JSON.parse(text));
    } catch {
        return null;
    }
}

@Component({
    standalone: true,
    selector: 'app-domain-dialog',
    imports: [CommonModule, JsonEditorComponent, DdlEditorComponent, OverlayModule, AppSvgIconComponent],
    encapsulation: ViewEncapsulation.None,
    template: `
        <div class="dialog-container">
            <div class="dialog-header">
                <h2 class="dialog-title">Domain Variables</h2>
                <button
                    class="close-button"
                    (click)="close()"
                >
                    <app-svg-icon icon="x"></app-svg-icon>
                </button>
            </div>

            <div class="dialog-tabs">
                <button
                    type="button"
                    class="tab-button"
                    [class.active]="activeTab() === 'schema'"
                    (click)="setActiveTab('schema')"
                >
                    <span>Schema</span>
                    <span class="ddl-chip">DDL</span>
                    @if (ddlDotSeverity(); as severity) {
                        <span
                            class="tab-dot"
                            [class.dot-error]="severity === 'error'"
                            [class.dot-warning]="severity === 'warning'"
                        ></span>
                    }
                </button>
                <button
                    type="button"
                    class="tab-button"
                    [class.active]="activeTab() === 'json'"
                    (click)="setActiveTab('json')"
                >
                    <span>JSON</span>
                    @if (jsonTabHasError()) {
                        <span class="tab-dot dot-error"></span>
                    }
                </button>
            </div>

            <div class="dialog-content">
                @if (activeTab() === 'schema') {
                    <div class="schema-tab">
                        <div class="autocomplete-hint">
                            <app-svg-icon
                                icon="bulb"
                                size="1rem"
                            ></app-svg-icon>
                            <span>
                                Classes defined here describe your Domain — the <code>domain</code> block's fields
                                become your <code>variables</code>. The sample pane on the right shows the
                                <code>variables</code> object this schema produces — edit it directly and new keys
                                are added back into the schema. Removing <code>context</code> from the domain block
                                will invalidate any saved persistent-variable paths.
                            </span>
                        </div>

                        <div class="schema-split">
                            <div class="schema-pane schema-pane-editor">
                                <app-ddl-editor
                                    [value]="ddlSourceText()"
                                    (valueChange)="onDdlSourceChange($event)"
                                    (diagnosticsChange)="onDdlDiagnosticsChange($event)"
                                    (schemaChange)="onDdlSchemaChange($event)"
                                ></app-ddl-editor>
                            </div>
                            <div class="schema-pane schema-pane-preview">
                                <div class="preview-header">
                                    <span class="preview-title">Sample variables (editable)</span>
                                    <button
                                        type="button"
                                        class="apply-button"
                                        [disabled]="applyDisabled()"
                                        [title]="applyDisabledReason()"
                                        (click)="applySample()"
                                    >
                                        Replace variables with sample
                                    </button>
                                </div>
                                <app-json-editor
                                    [jsonData]="paneJsonText()"
                                    [showHeader]="false"
                                    [fullHeight]="true"
                                    (jsonChange)="onPaneJsonChange($event)"
                                    (validationChange)="onPaneValidChange($event)"
                                ></app-json-editor>
                                <div class="preview-status">{{ ddlStatusMessage() }}</div>
                                @if (syncReportSummaryLine(); as summary) {
                                    <div class="sync-report">
                                        <button
                                            type="button"
                                            class="sync-report-toggle"
                                            (click)="syncReportExpanded.set(!syncReportExpanded())"
                                        >
                                            <app-svg-icon
                                                [icon]="syncReportExpanded() ? 'chevron-up' : 'chevron-down'"
                                                size="0.9rem"
                                            ></app-svg-icon>
                                            <span>{{ summary }}</span>
                                        </button>
                                        @if (syncReportExpanded()) {
                                            <ul class="sync-report-list">
                                                @for (
                                                    entry of syncReportEntries();
                                                    track entry.kind + entry.path + entry.message
                                                ) {
                                                    <li
                                                        class="sync-report-item"
                                                        [class.is-error]="
                                                            entry.kind === 'type-mismatch' || entry.kind === 'discarded'
                                                        "
                                                    >
                                                        <span class="sync-report-path">{{ entry.path || '(root)' }}</span>
                                                        <span class="sync-report-message">{{ entry.message }}</span>
                                                    </li>
                                                }
                                            </ul>
                                        }
                                    </div>
                                }
                            </div>
                        </div>
                    </div>
                } @else {
                    <div class="helper-text">
                        Here you can define your domain variables that will be available throughout your workflow execution.
                    </div>

                    <div class="autocomplete-hint">
                        <app-svg-icon
                            icon="bulb"
                            size="1rem"
                        ></app-svg-icon>
                        <span>
                            Place your cursor inside <code>user</code> or <code>organization</code> arrays and press
                            <kbd>Ctrl+Space</kbd> to pick variables from <code>context</code>.
                        </span>
                    </div>

                    @if (pathErrorMessages().length > 0) {
                        <ul class="path-validation-errors">
                            @for (message of pathErrorMessages(); track message) {
                                <li class="path-error">
                                    <app-svg-icon icon="alert-circle"></app-svg-icon>
                                    <span>{{ message }}</span>
                                </li>
                            }
                        </ul>
                    }
                    <div class="json-editor-section">
                        <app-json-editor
                            class="json-editor"
                            [jsonData]="initialStateJson"
                            (jsonChange)="onInitialStateChange($event)"
                            (validationChange)="onJsonValidChange($event)"
                            (editorReady)="onEditorReady($event)"
                            [fullHeight]="true"
                        ></app-json-editor>
                    </div>
                }
            </div>
        </div>
    `,
    styles: [
        `
            .dialog-container {
                display: flex;
                flex-direction: column;
                height: 100%;
                min-height: 0;
                background: var(--color-modals-background);
                border-radius: 12px;
                box-shadow:
                    0 12px 28px rgba(0, 0, 0, 0.4),
                    0 4px 8px rgba(0, 0, 0, 0.2);
                overflow: hidden;
            }

            .domain-dialog-panel {
                z-index: 9600 !important;
            }

            .dialog-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 1rem 1.5rem;
                border-bottom: 1px solid var(--color-divider-subtle, #444);
            }

            .dialog-title {
                font-size: 1.2rem;
                font-weight: 400;
                color: var(--color-text-primary, #fff);
                margin: 0;
            }

            .close-button {
                background: none;
                border: none;
                color: var(--color-text-secondary, #aaa);
                cursor: pointer;
                padding: 0.5rem;
                border-radius: 4px;
                transition: all 0.2s ease;
                display: flex;
                align-items: center;
                justify-content: center;
                line-height: 1;

                &:hover {
                    background: var(--color-surface-hover, #333);
                    color: var(--color-text-primary, #fff);
                }
            }

            .dialog-tabs {
                display: flex;
                gap: 0.25rem;
                padding: 0 1.5rem;
                border-bottom: 1px solid var(--color-divider-subtle, #444);
                flex-shrink: 0;
            }

            .tab-button {
                display: flex;
                align-items: center;
                gap: 0.4rem;
                background: none;
                border: none;
                border-bottom: 2px solid transparent;
                color: var(--color-text-secondary, #aaa);
                font-size: 0.875rem;
                padding: 0.65rem 0.25rem;
                margin-bottom: -1px;
                cursor: pointer;
                transition: color 0.2s ease, border-color 0.2s ease;

                &:hover {
                    color: var(--color-text-primary, #fff);
                }

                &.active {
                    color: var(--accent-color, #685fff);
                    border-bottom-color: var(--accent-color, #685fff);
                }
            }

            .ddl-chip {
                font-size: 0.65rem;
                font-weight: 600;
                letter-spacing: 0.03em;
                padding: 0.1em 0.4em;
                border-radius: 3px;
                background: rgba(101, 98, 245, 0.18);
                color: #a5a5ff;
            }

            .tab-dot {
                width: 6px;
                height: 6px;
                border-radius: 50%;
                background: #f59e0b;

                &.dot-error {
                    background: #ef4444;
                }

                &.dot-warning {
                    background: #f59e0b;
                }
            }

            .dialog-content {
                flex: 1;
                padding: 1.5rem;
                overflow: hidden;
                display: flex;
                flex-direction: column;
            }

            .schema-tab {
                display: flex;
                flex-direction: column;
                flex: 1;
                min-height: 0;
            }

            .schema-split {
                flex: 1;
                min-height: 0;
                display: grid;
                grid-template-columns: 1.15fr 1fr;
                gap: 1rem;

                @media (max-width: 860px) {
                    grid-template-columns: 1fr;
                }
            }

            .schema-pane {
                display: flex;
                flex-direction: column;
                min-height: 0;
                min-width: 0;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                overflow: hidden;
            }

            .schema-pane-editor {
                app-ddl-editor {
                    flex: 1;
                    min-height: 0;
                    display: block;
                }
            }

            .schema-pane-preview {
                background: var(--gray-850);
                padding: 0.85rem 1rem;

                app-json-editor {
                    flex: 1;
                    min-height: 0;
                    display: block;
                    border-radius: 6px;
                    overflow: hidden;
                }
            }

            .preview-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 0.75rem;
                margin-bottom: 0.6rem;
            }

            .preview-title {
                font-size: 0.8rem;
                font-weight: 500;
                color: var(--color-text-secondary, #aaa);
                text-transform: uppercase;
                letter-spacing: 0.03em;
            }

            .apply-button {
                background: var(--accent-color, #685fff);
                color: #fff;
                border: none;
                border-radius: 6px;
                padding: 0.4rem 0.75rem;
                font-size: 0.78rem;
                cursor: pointer;
                white-space: nowrap;
                transition: opacity 0.2s ease;

                &:hover:not(:disabled) {
                    opacity: 0.9;
                }

                &:disabled {
                    background: var(--color-surface-hover, #333);
                    color: var(--color-text-secondary, #aaa);
                    cursor: not-allowed;
                }
            }

            .preview-status {
                margin-top: 0.6rem;
                font-size: 0.75rem;
                color: var(--color-text-secondary, #aaa);
                line-height: 1.4;
            }

            .sync-report {
                margin-top: 0.5rem;
            }

            .sync-report-toggle {
                display: flex;
                align-items: center;
                gap: 0.35rem;
                background: none;
                border: none;
                padding: 0;
                color: var(--color-text-secondary, #aaa);
                font-size: 0.75rem;
                cursor: pointer;
                text-align: left;

                &:hover {
                    color: var(--color-text-primary, #fff);
                }
            }

            .sync-report-list {
                margin: 0.4rem 0 0;
                padding: 0.5rem 0.65rem;
                list-style: none;
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                max-height: 160px;
                overflow-y: auto;
            }

            .sync-report-item {
                display: flex;
                flex-direction: column;
                gap: 0.1rem;
                padding: 0.3rem 0;
                font-size: 0.72rem;
                line-height: 1.35;
                color: var(--color-text-secondary, #aaa);
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);

                &:last-child {
                    border-bottom: none;
                }

                &.is-error {
                    color: var(--color-error);
                }
            }

            .sync-report-path {
                font-family: 'JetBrains Mono', monospace;
                color: #a5a5ff;
            }

            .sync-report-message {
                color: inherit;
            }

            .helper-text {
                color: #6b7280;
                font-size: 0.875rem;
                line-height: 1.4;
                margin-bottom: 0.75rem;
            }

            .autocomplete-hint {
                display: flex;
                align-items: flex-start;
                gap: 0.6rem;
                padding: 0.6rem 0.85rem;
                margin-bottom: 1rem;
                background: rgba(101, 98, 245, 0.08);
                border: 1px solid rgba(101, 98, 245, 0.2);
                border-radius: 6px;
                font-size: 0.8rem;
                line-height: 1.45;
                color: #b0b0c0;

                app-svg-icon {
                    color: #685fff;
                    flex-shrink: 0;
                    margin-top: 1px;
                }

                kbd {
                    background: rgba(255, 255, 255, 0.1);
                    border: 1px solid rgba(255, 255, 255, 0.18);
                    border-radius: 3px;
                    padding: 0.1em 0.4em;
                    font-size: 0.85em;
                    font-family: inherit;
                    color: #d0d0e0;
                }

                code {
                    background: rgba(101, 98, 245, 0.18);
                    border-radius: 3px;
                    padding: 0.1em 0.35em;
                    font-size: 0.9em;
                    color: #a5a5ff;
                }
            }

            .path-validation-errors {
                padding: 0.5rem 0.75rem;
                margin-bottom: 1rem;
                background: rgba(239, 68, 68, 0.1);
                border: 1px solid rgba(239, 68, 68, 0.3);
                border-radius: 6px;
                font-size: 0.8rem;
            }

            .path-error {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                color: #f87171;
                line-height: 1.4;

                app-svg-icon {
                    flex-shrink: 0;
                    margin-top: 2px;
                }

                span {
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 0.85em;
                }
            }

            .json-editor-section {
                flex: 1;
                min-height: 400px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                overflow: hidden;
            }

            .json-editor {
                height: 100%;
            }

            .dialog-actions {
                display: flex;
                justify-content: flex-end;
                gap: 0.75rem;
                padding: 1rem 1.5rem;
                border-top: 1px solid var(--color-divider-subtle, #444);
            }
        `,
    ],
})
export class DomainDialogComponent implements OnDestroy {
    public initialStateJson: string = '{}';
    public isJsonValid: boolean = true;
    public validationResult = signal<PersistentVariablesValidationResult>(EMPTY_VALIDATION_RESULT);

    public hasPathErrors = computed(() => hasValidationErrors(this.validationResult()));
    public pathErrorMessages = computed(() => formatValidationMessages(this.validationResult()));

    // --- Schema (DDL) tab state ---
    public readonly activeTab = signal<DomainDialogTab>('json');
    public readonly ddlSourceText = signal<string>('');
    public readonly ddlDiagnostics = signal<Diagnostic[]>([]);
    public readonly ddlGenerateResult = signal<GenerateResult | null>(null);

    /** The editable "sample variables" pane — source of truth for the JSON→DDL merge direction. */
    public readonly paneJsonText = signal<string>('{}');
    /** Mirrors the pane json-editor's own JSON.parse validity check (drives `applyDisabled`/status). */
    public readonly paneJsonValid = signal<boolean>(true);
    /** Most recent additive-merge report (skipped keys, type mismatches, removed keys). `null` when nothing to show. */
    public readonly syncReport = signal<SyncReport | null>(null);
    public readonly syncReportExpanded = signal(false);

    /** Set only when the user clicks "Replace variables with sample" — drives the status line. Canonical (parsed+stringified) pane value. */
    public readonly lastAppliedSampleJson = signal<string | null>(null);

    public readonly ddlHasErrorDiagnostics = computed(() => this.ddlDiagnostics().some((d) => d.severity === 'error'));
    public readonly ddlHasWarningDiagnostics = computed(() =>
        this.ddlDiagnostics().some((d) => d.severity === 'warning')
    );
    public readonly ddlDotSeverity = computed<'error' | 'warning' | null>(() => {
        if (this.ddlHasErrorDiagnostics()) return 'error';
        if (this.ddlHasWarningDiagnostics()) return 'warning';
        return null;
    });

    /** The pane's parsed value, or `undefined` while it holds invalid JSON. */
    private readonly paneParsedValue = computed<JsonValue | undefined>(() => {
        try {
            return JSON.parse(this.paneJsonText()) as JsonValue;
        } catch {
            return undefined;
        }
    });

    public readonly paneRootIsObject = computed<boolean>(() => {
        const value = this.paneParsedValue();
        return value !== undefined && isPlainJsonObject(value);
    });

    /** Canonical (parsed+stringified) form of the pane's current text, or `null` while it is invalid. */
    private readonly canonicalPaneJson = computed<string | null>(() => {
        const value = this.paneParsedValue();
        return value === undefined ? null : JSON.stringify(value);
    });

    public readonly applyDisabled = computed(
        () => this.ddlHasErrorDiagnostics() || !this.paneJsonValid() || !this.paneRootIsObject()
    );

    public readonly applyDisabledReason = computed<string>(() => {
        if (this.ddlHasErrorDiagnostics()) return 'Fix schema errors to apply';
        if (!this.paneJsonValid()) return 'Fix JSON errors in the sample pane to apply';
        if (!this.paneRootIsObject()) return 'JSON root must be an object to apply';
        return '';
    });

    public readonly ddlSyncStatus = computed<DdlSyncStatus>(() => {
        const applied = this.lastAppliedSampleJson();
        if (applied === null) return 'never';
        const current = this.canonicalPaneJson();
        return current !== null && current === applied ? 'in-sync' : 'stale';
    });

    // First applicable message wins: schema errors, invalid pane JSON, non-object root, then sync status.
    public readonly ddlStatusMessage = computed(() => {
        if (this.ddlHasErrorDiagnostics()) return 'Sync paused — schema has errors.';
        if (!this.paneJsonValid()) return 'Sync paused — the sample pane has invalid JSON.';
        if (!this.paneRootIsObject()) return 'JSON root must be an object.';

        switch (this.ddlSyncStatus()) {
            case 'in-sync':
                return '✓ In sync with the JSON tab';
            case 'stale':
                return 'Schema changed since last apply — JSON tab still holds the previous variables';
            default:
                return 'Sample pane updates live — persistent_variables are never touched';
        }
    });

    public readonly syncReportEntries = computed<SyncReportEntry[]>(() => this.syncReport()?.entries ?? []);

    public readonly syncReportSummaryLine = computed<string | null>(() => {
        const entries = this.syncReportEntries();
        if (entries.length === 0) return null;

        const counts = new Map<SyncEntryKind, number>();
        for (const entry of entries) {
            counts.set(entry.kind, (counts.get(entry.kind) ?? 0) + 1);
        }

        const skippedInvalid = counts.get('skipped-invalid-key') ?? 0;
        const skippedEmpty = counts.get('skipped-empty-object') ?? 0;
        const mismatches = counts.get('type-mismatch') ?? 0;
        const removed = counts.get('removed-key') ?? 0;
        const discarded = counts.get('discarded') ?? 0;

        const parts: string[] = [];
        if (skippedInvalid > 0) parts.push(`${skippedInvalid} invalid key${skippedInvalid > 1 ? 's' : ''} skipped`);
        if (skippedEmpty > 0) parts.push(`${skippedEmpty} empty object${skippedEmpty > 1 ? 's' : ''} skipped`);
        if (mismatches > 0) parts.push(`${mismatches} type mismatch${mismatches > 1 ? 'es' : ''}`);
        if (removed > 0) parts.push(`${removed} key${removed > 1 ? 's' : ''} missing from JSON`);
        if (discarded > 0) parts.push('sync issue — see details');

        return parts.length > 0 ? parts.join(' · ') : null;
    });

    /**
     * Baseline for the close-time auto-apply diff check and the "in sync" status: the
     * canonical (parsed+stringified) pane value that is already reflected in `variables`
     * (seeded on first entry into the Schema tab, refreshed on every apply). Not shown
     * directly in the UI — `lastAppliedSampleJson` drives the status line.
     */
    private baselineSampleJson: string | null = null;

    // --- Direction-lock state machine bookkeeping ---
    /** Number of upcoming `schemaChange` events that are echoes of our own merge pushes, not user edits. */
    private expectedDdlEchoes = 0;
    /** True once the first (seeding) `schemaChange` after entering the Schema tab has been handled. */
    private schemaTabSeeded = false;
    /** Timestamp of the pane's last user-typed `jsonChange`, or `null` if untouched since the tab was entered. */
    private lastPaneEditAt: number | null = null;
    private mergeTimerId: ReturnType<typeof setTimeout> | null = null;

    private monacoEditor: import('monaco-editor').editor.IStandaloneCodeEditor | null = null;
    private overlayService = inject(Overlay);
    private viewContainerRef = inject(ViewContainerRef);
    private overlayRef: OverlayRef | null = null;
    private autocompleteInstance: AutocompleteOverlayComponent | null = null;
    private currentPath: string[] = [];
    private currentTargetArray: 'user' | 'organization' | null = null;
    private contextObject: Record<string, unknown> | null = null;
    private keyDownDisposable: import('monaco-editor').IDisposable | null = null;
    private cursorDisposable: import('monaco-editor').IDisposable | null = null;
    private destroyRef = inject(DestroyRef);

    constructor(
        private dialogRef: DialogRef<DomainDialogResult | null>,
        @Inject(DIALOG_DATA) public data: DomainDialogData
    ) {
        this.initializeJsonEditor();
        this.initializeDdlTab();

        this.dialogRef.backdropClick.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.close());

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.code === 'KeyS') {
                if (this.overlayRef?.hasAttached()) return;
                e.preventDefault();
                this.close();
                return;
            }
            if (e.key === 'Escape') {
                if (this.overlayRef?.hasAttached()) return;
                e.preventDefault();
                this.close();
            }
        });
    }

    ngOnDestroy(): void {
        this.closeOverlay();
        this.keyDownDisposable?.dispose();
        this.cursorDisposable?.dispose();
        this.clearMergeTimer();
    }

    // --- JSON Editor setup ---

    public onInitialStateChange(json: string): void {
        this.initialStateJson = json;
        this.validatePathsInPersistentVariables(json);
    }

    public onJsonValidChange(isValid: boolean): void {
        this.isJsonValid = isValid;
    }

    public close(): void {
        this.flushPendingMerge();
        this.autoApplyDdlIfNeeded();

        if (!this.isJsonValid || this.hasPathErrors()) return;

        const ddlSource = this.ddlSourceText();
        this.dialogRef.close({
            initialState: this.buildResult(),
            ddlSource: ddlSource.trim().length > 0 ? ddlSource : null,
        });
    }

    /** True if the JSON tab currently has an error state — drives its tab-label dot. */
    public jsonTabHasError(): boolean {
        return !this.isJsonValid || this.hasPathErrors();
    }

    // --- Tab switching ---

    /**
     * Switching tabs destroys/recreates both Schema-tab editors (`@if`), so any in-flight
     * pane-merge state from the previous activation is no longer meaningful. Entering the
     * Schema tab additionally resets the seeding/echo bookkeeping so the next `schemaChange`
     * is treated as a fresh seed from the JSON tab's current `variables` — which always wins
     * on (re)entry.
     */
    public setActiveTab(tab: DomainDialogTab): void {
        this.clearMergeTimer();
        if (tab === 'schema') {
            this.resetSchemaSyncState();
            this.syncReport.set(null);
        }
        this.activeTab.set(tab);
    }

    // --- Schema (DDL) tab handlers ---

    public onDdlSourceChange(source: string): void {
        this.ddlSourceText.set(source);
    }

    public onDdlDiagnosticsChange(diagnostics: Diagnostic[]): void {
        this.ddlDiagnostics.set(diagnostics);
    }

    /**
     * Direction-lock state machine entry point for DDL→pane sync. Exactly one of three
     * branches runs per compile:
     *  1. Echo of our own merge push (`expectedDdlEchoes > 0`) — decrement and stop; the
     *     pane already holds the value that produced this compile.
     *  2. First compile after entering the Schema tab (`!schemaTabSeeded`) — the JSON tab's
     *     `variables` wins: seed the pane and baseline from it, then run one immediate
     *     catch-up merge so any keys the JSON tab has that the schema doesn't yet know about
     *     are added right away.
     *  3. Otherwise the user typed DDL directly — reshape the pane onto the new sample while
     *     preserving values, unless a pane edit is in flight (recent keystroke or a merge
     *     debounce still pending), in which case that pending merge will reconcile instead.
     */
    public onDdlSchemaChange(result: GenerateResult): void {
        this.ddlGenerateResult.set(result);

        if (this.expectedDdlEchoes > 0) {
            this.expectedDdlEchoes--;
            return;
        }

        if (!this.schemaTabSeeded) {
            this.schemaTabSeeded = true;
            this.seedPaneFromJsonTab();
            this.attemptMergePaneIntoDdl(result);
            return;
        }

        if (this.isPaneEditPendingOrRecent()) return;

        this.reconcilePaneFromDdlSample(result);
    }

    // --- Pane (editable sample) handlers — JSON→DDL merge direction ---

    public onPaneJsonChange(json: string): void {
        this.paneJsonText.set(json);
        this.lastPaneEditAt = Date.now();
        this.scheduleMerge();
    }

    public onPaneValidChange(valid: boolean): void {
        this.paneJsonValid.set(valid);
    }

    // --- Apply ---

    public applySample(): void {
        if (this.applyDisabled()) return;
        if (this.commitPaneToVariables()) {
            this.lastAppliedSampleJson.set(this.canonicalPaneJson());
        }
    }

    // --- Monaco editor & autocomplete setup ---

    public onEditorReady(editor: import('monaco-editor').editor.IStandaloneCodeEditor): void {
        this.monacoEditor = editor;
        this.setupAutocomplete();
    }

    // --- JSON Editor setup ---

    private initializeJsonEditor(): void {
        const initial = this.data?.initialData as Record<string, unknown> | undefined;
        const isEmptyObject =
            initial && typeof initial === 'object' && !Array.isArray(initial)
                ? Object.keys(initial).length === 0
                : true;

        if (initial && !isEmptyObject) {
            try {
                this.initialStateJson = JSON.stringify(initial, null, 2);
                this.isJsonValid = true;
            } catch {
                this.initialStateJson = JSON.stringify(DEFAULT_INITIAL_STATE, null, 2);
                this.isJsonValid = false;
            }
        } else {
            this.initialStateJson = JSON.stringify(DEFAULT_INITIAL_STATE, null, 2);
            this.isJsonValid = true;
        }
        this.validatePathsInPersistentVariables(this.initialStateJson);
    }

    private initializeDdlTab(): void {
        const ddlSource = typeof this.data?.ddlSource === 'string' ? this.data.ddlSource : '';
        this.ddlSourceText.set(ddlSource);
        this.resetSchemaSyncState();
        this.activeTab.set(ddlSource.trim().length > 0 ? 'schema' : 'json');
    }

    private validatePathsInPersistentVariables(json: string): void {
        this.validationResult.set(validatePersistentVariables(json));
    }

    private buildResult(): Record<string, unknown> {
        if (!this.isJsonValid) throw new Error('Invalid JSON');

        try {
            let parsed: unknown = JSON.parse(this.initialStateJson);

            if (
                parsed &&
                typeof parsed === 'object' &&
                !Array.isArray(parsed) &&
                Object.keys(parsed as Record<string, unknown>).length === 0
            ) {
                parsed = { context: null };
            }

            return parsed as Record<string, unknown>;
        } catch {
            return { context: null };
        }
    }

    // --- Tab switching ---

    private resetSchemaSyncState(): void {
        this.schemaTabSeeded = false;
        this.expectedDdlEchoes = 0;
        this.lastPaneEditAt = null;
    }

    // --- Schema (DDL) tab handlers ---

    /** Seeds the pane (and the close-time baseline) from the JSON tab's current `variables` — JSON tab wins on entry. */
    private seedPaneFromJsonTab(): void {
        const doc = this.parseJsonLenient(this.initialStateJson);
        const variables = doc?.['variables'];
        const seeded: JsonObject = isPlainJsonObject(variables) ? variables : {};
        const seededText = JSON.stringify(seeded, null, 2);

        this.paneJsonText.set(seededText);
        this.baselineSampleJson = canonicalizeJson(seededText);
    }

    private isPaneEditPendingOrRecent(): boolean {
        if (this.mergeTimerId !== null) return true;
        if (this.lastPaneEditAt === null) return false;
        return Date.now() - this.lastPaneEditAt < RECENT_PANE_EDIT_THRESHOLD_MS;
    }

    /** Reshapes the pane onto the DDL-generated sample's shape while preserving the user's current values. */
    private reconcilePaneFromDdlSample(result: GenerateResult): void {
        const userValue = this.paneParsedValue();
        if (userValue === undefined) return; // pane currently holds invalid JSON — leave it for the user to fix

        let sampleValue: JsonValue;
        try {
            sampleValue = JSON.parse(result.json) as JsonValue;
        } catch {
            return; // defensive — emitJson always produces valid JSON
        }

        const conformed = conformValuesToSample(sampleValue, userValue);
        this.paneJsonText.set(JSON.stringify(conformed, null, 2));
    }

    // --- Pane (editable sample) handlers — JSON→DDL merge direction ---

    private scheduleMerge(): void {
        this.clearMergeTimer();
        this.mergeTimerId = setTimeout(() => {
            this.mergeTimerId = null;
            this.attemptMergePaneIntoDdl(this.ddlGenerateResult());
        }, PANE_MERGE_DEBOUNCE_MS);
    }

    private clearMergeTimer(): void {
        if (this.mergeTimerId !== null) {
            clearTimeout(this.mergeTimerId);
            this.mergeTimerId = null;
        }
    }

    /** Runs any pending debounced merge immediately and synchronously — used by `close()` so nothing is lost on exit. */
    private flushPendingMerge(): void {
        if (this.mergeTimerId === null) return;
        this.clearMergeTimer();
        this.attemptMergePaneIntoDdl(this.ddlGenerateResult());
    }

    /**
     * Additively merges the pane's current JSON into the DDL source, guarded in order by:
     * an empty/whitespace pane (skip, clear the report — nothing to merge), invalid pane
     * JSON (skip silently — mid-typing), a non-object pane root, and a broken schema (both
     * surfaced via `ddlStatusMessage`, so the report itself is cleared rather than duplicated).
     * A successful, changed merge bumps `expectedDdlEchoes` before pushing the updated source,
     * so the compile it triggers is recognized as an echo rather than a user DDL edit.
     */
    private attemptMergePaneIntoDdl(generateResult: GenerateResult | null): void {
        const paneText = this.paneJsonText();
        if (paneText.trim().length === 0) {
            this.syncReport.set(null);
            return;
        }

        const parsedPane = this.paneParsedValue();
        if (parsedPane === undefined) return; // invalid JSON mid-typing — no churn

        if (!isPlainJsonObject(parsedPane)) {
            this.syncReport.set(null); // ddlStatusMessage already surfaces "JSON root must be an object"
            return;
        }

        if (!generateResult || generateResult.schema.hasErrors) {
            this.syncReport.set(null); // ddlStatusMessage already surfaces "sync paused — schema has errors"
            return;
        }

        const mergeResult = mergeJsonIntoDdl(this.ddlSourceText(), generateResult.schema, parsedPane);
        this.syncReport.set(mergeResult.report);

        if (mergeResult.changed) {
            this.expectedDdlEchoes++;
            this.ddlSourceText.set(mergeResult.updatedSource);
        }
    }

    // --- Apply ---

    /**
     * Parses the pane's current JSON and replaces `variables` wholesale in the working JSON
     * document, leaving `persistent_variables` and any other top-level keys untouched.
     * No-ops (returns `false`) if the pane is not currently a valid JSON object — callers
     * gate on `applyDisabled()`/`paneRootIsObject()` first, this is a defensive safety net.
     */
    private commitPaneToVariables(): boolean {
        const paneVariables = this.paneParsedValue();
        if (paneVariables === undefined || !isPlainJsonObject(paneVariables)) return false;

        const currentDoc = this.parseJsonLenient(this.initialStateJson) ?? {};
        const updatedDoc: Record<string, unknown> = { ...currentDoc, variables: paneVariables };
        const updatedJson = JSON.stringify(updatedDoc, null, 2);

        this.initialStateJson = updatedJson;
        this.isJsonValid = true;
        this.validatePathsInPersistentVariables(updatedJson);
        this.baselineSampleJson = this.canonicalPaneJson();
        return true;
    }

    /**
     * Auto-applies the pane's current value once on close if the schema tab was engaged
     * (non-empty DDL source), the pane is currently in an "apply-able" state (same gate as
     * the button), and it has drifted from what is already reflected in `variables`. A
     * broken schema or invalid/non-object pane never blocks saving and never corrupts
     * `variables` — they are left exactly as-is.
     */
    private autoApplyDdlIfNeeded(): void {
        if (this.ddlSourceText().trim().length === 0) return;
        if (this.applyDisabled()) return;

        const canonical = this.canonicalPaneJson();
        if (canonical === null || canonical === this.baselineSampleJson) return;

        this.commitPaneToVariables();
    }

    // --- Monaco editor & autocomplete setup ---

    private getEditorContext(): {
        editor: import('monaco-editor').editor.IStandaloneCodeEditor;
        model: import('monaco-editor').editor.ITextModel;
        position: import('monaco-editor').Position;
    } | null {
        const editor = this.monacoEditor;
        if (!editor) return null;
        const model = editor.getModel();
        const position = editor.getPosition();
        if (!model || !position) return null;
        return { editor, model, position };
    }

    private setupAutocomplete(): void {
        if (!this.monacoEditor) return;

        this.monacoEditor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Space, () => this.handleCtrlSpace());

        this.keyDownDisposable = this.monacoEditor.onKeyDown((e: import('monaco-editor').IKeyboardEvent) => {
            if (!this.overlayRef?.hasAttached() || !this.autocompleteInstance) return;

            const key = e.browserEvent.key;

            if (key === 'ArrowDown') {
                e.preventDefault();
                e.stopPropagation();
                this.autocompleteInstance.navigateNext();
            } else if (key === 'ArrowUp') {
                e.preventDefault();
                e.stopPropagation();
                this.autocompleteInstance.navigatePrev();
            } else if (key === 'Enter' || key === 'Tab') {
                e.preventDefault();
                e.stopPropagation();
                this.autocompleteInstance.selectActive();
            } else if (key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                this.closeOverlay();
            } else if (key === 'ArrowRight') {
                e.preventDefault();
                e.stopPropagation();
                const active = this.autocompleteInstance.activeItem();
                if (active && active.type === 'group') {
                    this.onNavigateDown(active);
                }
            } else if (key === 'ArrowLeft') {
                e.preventDefault();
                e.stopPropagation();
                if (this.currentPath.length > 0) {
                    this.onNavigateUp();
                }
            }
        });

        this.cursorDisposable = this.monacoEditor.onDidChangeCursorPosition(() => {
            if (!this.overlayRef?.hasAttached()) return;
            const ctx = this.getEditorContext();
            if (!ctx) return;
            const offset = ctx.model.getOffsetAt(ctx.position);
            const text = ctx.model.getValue();

            if (!this.isCursorInTargetArray(text, offset)) {
                this.closeOverlay();
            }
        });
    }

    // --- Ctrl+Space handler ---

    private handleCtrlSpace(): void {
        if (this.overlayRef?.hasAttached()) {
            this.closeOverlay();
            return;
        }

        const ctx = this.getEditorContext();
        if (!ctx) return;
        const offset = ctx.model.getOffsetAt(ctx.position);
        const text = ctx.model.getValue();

        const targetArray = this.getCursorTargetArray(text, offset);
        if (targetArray) {
            this.currentTargetArray = targetArray;
            const contextObj = this.extractContextObject(text);
            if (
                contextObj &&
                typeof contextObj === 'object' &&
                Object.keys(contextObj as Record<string, unknown>).length > 0
            ) {
                this.contextObject = contextObj as Record<string, unknown>;
                this.currentPath = [];
                this.openOverlay();
            } else {
                this.contextObject = null;
                this.currentPath = [];
                this.openOverlay(
                    'Define variables inside "context" object first, then use Ctrl+Space here to pick them.'
                );
            }
        } else {
            this.currentTargetArray = null;
            ctx.editor.trigger('keyboard', 'editor.action.triggerSuggest', {});
        }
    }

    // --- Cursor position detection via jsonc-parser ---

    private readonly parseOptions = { allowTrailingComma: true } as const;

    private getCursorTargetArray(text: string, offset: number): 'user' | 'organization' | null {
        const root = parseTree(text, [], this.parseOptions);
        if (!root) return null;

        const node = findNodeAtOffset(root, offset, true);
        if (!node) return null;

        let current: JsonNode | undefined = node;
        while (current) {
            if (current.type === 'array' && current.parent) {
                const prop = current.parent;
                if (prop.type === 'property' && prop.children && prop.children.length > 0) {
                    const keyNode = prop.children[0];
                    if (keyNode.type === 'string') {
                        const arrName = keyNode.value;
                        if (arrName === 'user' || arrName === 'organization') {
                            const grandParent = prop.parent;
                            if (grandParent?.type === 'object' && grandParent.parent) {
                                const pvProp = grandParent.parent;
                                if (
                                    pvProp.type === 'property' &&
                                    pvProp.children?.[0]?.value === 'persistent_variables'
                                ) {
                                    return arrName as 'user' | 'organization';
                                }
                            }
                        }
                    }
                }
            }
            current = current.parent;
        }
        return null;
    }

    private isCursorInTargetArray(text: string, offset: number): boolean {
        return this.getCursorTargetArray(text, offset) !== null;
    }

    private parseJsonLenient(text: string): Record<string, unknown> | null {
        try {
            return JSON.parse(text) as Record<string, unknown>;
        } catch {
            try {
                return parseJsonc(text, [], this.parseOptions) as Record<string, unknown>;
            } catch {
                return null;
            }
        }
    }

    private extractContextObject(text: string): unknown {
        const parsed = this.parseJsonLenient(text);
        const variables = parsed?.['variables'] as Record<string, unknown> | undefined;
        return variables && typeof variables === 'object' ? variables['context'] : null;
    }

    private getPathsFromOppositeArray(): Set<string> {
        if (!this.currentTargetArray) return new Set();
        try {
            const parsed = this.parseJsonLenient(this.initialStateJson);
            if (!parsed) return new Set();
            const pv = parsed['persistent_variables'];
            if (!pv || typeof pv !== 'object') return new Set();
            const oppositeKey = this.currentTargetArray === 'user' ? 'organization' : 'user';
            return extractPathsFromArray((pv as Record<string, unknown>)[oppositeKey]);
        } catch {
            return new Set();
        }
    }

    private getPathsFromCurrentArray(): Set<string> {
        if (!this.currentTargetArray) return new Set();
        try {
            const parsed = this.parseJsonLenient(this.initialStateJson);
            if (!parsed) return new Set();
            const pv = parsed['persistent_variables'];
            if (!pv || typeof pv !== 'object') return new Set();
            return extractPathsFromArray((pv as Record<string, unknown>)[this.currentTargetArray]);
        } catch {
            return new Set();
        }
    }

    // --- Autocomplete items ---

    private buildAutocompleteItems(): AutocompleteItem[] {
        if (!this.contextObject) return [];

        let current: Record<string, unknown> | null = this.contextObject;
        for (const key of this.currentPath) {
            if (current && typeof current === 'object') {
                const next = current[key];
                if (next && typeof next === 'object' && !Array.isArray(next)) {
                    current = next as Record<string, unknown>;
                } else {
                    return [];
                }
            } else {
                return [];
            }
        }

        if (!current || typeof current !== 'object') return [];

        const oppositePaths = this.getPathsFromOppositeArray();
        const currentArrayPaths = this.getPathsFromCurrentArray();

        const obj = current;
        return Object.keys(obj)
            .map((key) => ({
                key,
                path: [...this.currentPath, key].join('.'),
                type: typeof obj[key] === 'object' && obj[key] !== null ? ('group' as const) : ('value' as const),
                value: obj[key],
            }))
            .filter((item) => {
                if (item.type === 'value') {
                    const fullPath = `context.${item.path}`;
                    return !oppositePaths.has(fullPath) && !currentArrayPaths.has(fullPath);
                }
                return true;
            });
    }

    // --- CDK Overlay management ---

    private openOverlay(emptyMessage?: string): void {
        if (this.overlayRef?.hasAttached()) {
            this.closeOverlay();
        }

        const ctx = this.getEditorContext();
        if (!ctx) return;
        const scrolledPos = ctx.editor.getScrolledVisiblePosition(ctx.position);
        const editorDom = ctx.editor.getDomNode();
        if (!scrolledPos || !editorDom) return;

        const positionStrategy = this.overlayService
            .position()
            .flexibleConnectedTo(editorDom)
            .withPositions([
                {
                    originX: 'start',
                    originY: 'top',
                    overlayX: 'start',
                    overlayY: 'top',
                    offsetX: scrolledPos.left,
                    offsetY: scrolledPos.top + scrolledPos.height,
                },
                {
                    originX: 'start',
                    originY: 'top',
                    overlayX: 'start',
                    overlayY: 'bottom',
                    offsetX: scrolledPos.left,
                    offsetY: scrolledPos.top,
                },
            ])
            .withPush(true)
            .withViewportMargin(8);

        this.overlayRef = this.overlayService.create({
            positionStrategy,
            scrollStrategy: this.overlayService.scrollStrategies.reposition(),
            hasBackdrop: false,
        });

        const portal = new ComponentPortal(AutocompleteOverlayComponent, this.viewContainerRef);
        const componentRef = this.overlayRef.attach(portal);
        this.autocompleteInstance = componentRef.instance;

        const overlayEl = this.overlayRef.overlayElement;
        overlayEl.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();
            setTimeout(() => this.monacoEditor?.focus());
        });

        this.autocompleteInstance.itemSelected.subscribe((item: AutocompleteItem) => this.onItemSelect(item));
        this.autocompleteInstance.navigateUp.subscribe(() => this.onNavigateUp());
        this.autocompleteInstance.navigateDown.subscribe((item: AutocompleteItem) => this.onNavigateDown(item));
        this.autocompleteInstance.navigateToPath.subscribe((index: number) => this.onNavigateToPath(index));

        const items = this.buildAutocompleteItems();
        this.autocompleteInstance.updateData(items, this.currentPath, '', 'context', emptyMessage);
    }

    private closeOverlay(): void {
        if (this.overlayRef) {
            this.overlayRef.dispose();
            this.overlayRef = null;
            this.autocompleteInstance = null;
        }
    }

    // --- Item selection & insertion ---

    private onItemSelect(item: AutocompleteItem): void {
        const ctx = this.getEditorContext();
        if (!ctx) return;
        const offset = ctx.model.getOffsetAt(ctx.position);
        const text = ctx.model.getValue();

        const insertValue = `context.${item.path}`;

        const root = parseTree(text, [], this.parseOptions);
        const nodeAtCursor = root ? findNodeAtOffset(root, offset, true) : undefined;
        const stringNode = this.findEnclosingStringNode(nodeAtCursor);

        if (stringNode) {
            const startPos = ctx.model.getPositionAt(stringNode.offset + 1);
            const endPos = ctx.model.getPositionAt(stringNode.offset + stringNode.length - 1);
            ctx.editor.executeEdits('autocomplete', [
                {
                    range: new monaco.Range(startPos.lineNumber, startPos.column, endPos.lineNumber, endPos.column),
                    text: insertValue,
                },
            ]);
        } else {
            const prefix = this.needsCommaBeforeInsert(text, offset) ? ', ' : '';
            ctx.editor.executeEdits('autocomplete', [
                {
                    range: new monaco.Range(
                        ctx.position.lineNumber,
                        ctx.position.column,
                        ctx.position.lineNumber,
                        ctx.position.column
                    ),
                    text: `${prefix}"${insertValue}"`,
                },
            ]);
        }

        this.closeOverlay();
        this.monacoEditor?.focus();
    }

    /** True if the character immediately before offset is end of a value (we need comma before new element). */
    private needsCommaBeforeInsert(text: string, offset: number): boolean {
        if (offset <= 0) return false;
        let i = offset - 1;
        while (i >= 0 && /\s/.test(text[i])) i--;
        if (i < 0) return false;
        const last = text[i];
        return last === '"' || last === ']' || last === '}' || /\d/.test(last);
    }

    private findEnclosingStringNode(node: JsonNode | undefined): JsonNode | null {
        let current = node;
        while (current) {
            if (current.type === 'string') return current;
            current = current.parent;
        }
        return null;
    }

    // --- Hierarchical navigation ---

    private onNavigateDown(item: AutocompleteItem): void {
        this.currentPath = [...this.currentPath, item.key];
        this.updateOverlayData();
    }

    private onNavigateUp(): void {
        if (this.currentPath.length === 0) return;
        this.currentPath = this.currentPath.slice(0, -1);
        this.updateOverlayData();
    }

    private onNavigateToPath(index: number): void {
        if (index === -1) {
            this.currentPath = [];
        } else {
            this.currentPath = this.currentPath.slice(0, index + 1);
        }
        this.updateOverlayData();
    }

    private updateOverlayData(): void {
        if (!this.autocompleteInstance) return;
        const items = this.buildAutocompleteItems();
        this.autocompleteInstance.updateData(items, this.currentPath, '', 'context');
    }
}
