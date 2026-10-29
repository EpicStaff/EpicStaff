import { computed, inject, Signal, signal } from '@angular/core';

import { TestRunNodeType } from '../../../../../features/flows/models/run-session.model';
import { ToastService } from '../../../../../services/notifications';
import { FlowTestRunService } from '../../../../services/flow-test-run.service';
import {
    checkTestPayloadText,
    describeTestRunBlocker,
    resolveSavedTestPayload,
    TestPayloadValidator,
    TriggerTestPayload,
} from '../../../../utils/test-run';

const NO_SERVER_ERRORS: readonly string[] = [];

export const INVALID_TEST_PAYLOAD_NOT_SAVED_MESSAGE =
    'The test payload is not valid JSON, so it was not saved. The last saved payload is kept.';
export const TEST_PAYLOAD_SAVED_OTHER_CHANGES_NOT_SAVED_MESSAGE =
    "Test payload saved. Other changes weren't saved — this node has invalid fields.";

/** A trigger node: its test payload is `data.test_payload`. */
export interface TestPayloadNode {
    data: { test_payload: TriggerTestPayload };
}

/** `node` with only its test payload replaced. */
export function withTestPayload<T extends TestPayloadNode>(node: T, payload: TriggerTestPayload): T {
    return { ...node, data: { ...node.data, test_payload: payload } };
}

/**
 * The test payload editor state of one trigger node panel: the text, whether the user edited it,
 * what it parses to, the backend's errors for it and whether it can be run. Create it in a field
 * initializer (it injects `FlowTestRunService` and `ToastService`).
 */
export class TriggerTestPayloadState {
    private readonly testRun = inject(FlowTestRunService);
    private readonly toastService = inject(ToastService);

    private readonly textSignal = signal('{}');
    public readonly text: Signal<string> = this.textSignal.asReadonly();
    private readonly isEditedSignal = signal(false);
    /** False while the text is a seed or the saved payload; only edited text is stored on the node. */
    public readonly isEdited: Signal<boolean> = this.isEditedSignal.asReadonly();

    /** What the text parses to and why it cannot run; the section's error list and Run both read it. */
    public readonly check = computed(() => checkTestPayloadText(this.text(), this.validator()));
    /**
     * An edit that is not JSON the backend accepts: saving keeps the last saved payload, so the panel
     * counts it as an unsaved change until it is fixed or reset.
     */
    public readonly hasUnsavedInvalidEdit = computed(() => this.isEdited() && this.check().parseError !== null);
    public readonly serverErrors = computed(() => this.testRun.serverErrors().get(this.nodeId()) ?? NO_SERVER_ERRORS);
    public readonly isStarting = computed(() => this.testRun.runningNodeId() === this.nodeId());
    public readonly runBlocker = computed(() => describeTestRunBlocker(this.check(), this.testRun.isRunStarting()));

    constructor(
        private readonly nodeType: TestRunNodeType,
        private readonly nodeId: Signal<string>,
        private readonly validator: Signal<TestPayloadValidator | null> = signal(null)
    ) {}

    /** Shows `text` as not edited: the saved payload or a seed. */
    public reset(text: string): void {
        this.textSignal.set(text);
        this.isEditedSignal.set(false);
    }

    /** A user edit; it drops the backend errors that were about the previous text. */
    public edit(text: string): void {
        if (text === this.textSignal()) return;
        this.textSignal.set(text);
        this.isEditedSignal.set(true);
        this.testRun.clearServerErrors(this.nodeId());
    }

    /**
     * Text a panel action wrote for the user (e.g. Insert example). Unlike `edit` it counts as edited
     * and drops the backend errors even when the text is unchanged: an unedited seed equal to it is
     * then saved.
     */
    public replace(text: string): void {
        this.textSignal.set(text);
        this.isEditedSignal.set(true);
        this.testRun.clearServerErrors(this.nodeId());
    }

    /** The payload to store on the node, given the one it has saved. Text that does not parse never replaces it. */
    public payloadToSave(savedPayload: TriggerTestPayload | undefined): TriggerTestPayload {
        return resolveSavedTestPayload(this.check(), this.isEdited(), savedPayload);
    }

    /**
     * The payload to save on its own while the node's other fields are invalid: the edited payload
     * when it parses and is not `savedPayload` already, else null. Rule errors do not block it, as
     * they do not block a full save.
     */
    public editToSaveAlone(savedPayload: TriggerTestPayload): TriggerTestPayload | null {
        const payload = this.check().payload;
        if (!this.isEdited() || payload === null) return null;
        return JSON.stringify(payload) === JSON.stringify(savedPayload) ? null : payload;
    }

    /**
     * Warns that only the payload was saved because the node has invalid fields (the panel may be
     * closing). Silent when the payload was the only edit: nothing was dropped.
     */
    public reportSavedAlone(hasOtherUnsavedEdits: boolean): void {
        if (hasOtherUnsavedEdits) {
            this.toastService.warning(TEST_PAYLOAD_SAVED_OTHER_CHANGES_NOT_SAVED_MESSAGE);
        }
    }

    /** Warns, after the whole node was saved, that an invalid edit was left out (the panel may be closing). */
    public reportInvalidEditNotSaved(): void {
        if (this.hasUnsavedInvalidEdit()) {
            this.toastService.warning(INVALID_TEST_PAYLOAD_NOT_SAVED_MESSAGE);
        }
    }

    /** Asks the flows page to save the graph and start a test run with the payload shown. */
    public run(): void {
        const payload = this.check().payload;
        if (payload === null || this.runBlocker() !== null) return;
        this.testRun.request(this.nodeType, this.nodeId(), payload);
    }
}
