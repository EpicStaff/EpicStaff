import { Injectable, Signal, signal } from '@angular/core';
import { Observable, Subject } from 'rxjs';

import { TestRunNodeType } from '../../features/flows/models/run-session.model';
import { TriggerTestPayload } from '../utils/test-run';

export interface FlowTestRunRequest {
    nodeType: TestRunNodeType;
    /** The canvas id of the trigger node (`NodeModel.id`), not its backend id. */
    nodeId: string;
    payload: TriggerTestPayload;
}

/**
 * The channel between a trigger node panel's "Run with test payload" button and the flows page
 * that saves the graph and starts the run (like `SidePanelService.requestSaveNode`). Also holds
 * what the panel shows about that run: whether a run is being started and the payload errors
 * the backend returned, per node.
 */
@Injectable({
    providedIn: 'root',
})
export class FlowTestRunService {
    private readonly requestsSubject = new Subject<FlowTestRunRequest>();
    public readonly requests$: Observable<FlowTestRunRequest> = this.requestsSubject.asObservable();

    private readonly isRunStartingSignal = signal(false);
    /** A regular or test run is being started (save, then the run request). Locks both run buttons. */
    public readonly isRunStarting: Signal<boolean> = this.isRunStartingSignal.asReadonly();

    private readonly runningNodeIdSignal = signal<string | null>(null);
    /** The canvas id of the trigger node whose test run is being started. */
    public readonly runningNodeId: Signal<string | null> = this.runningNodeIdSignal.asReadonly();

    private readonly serverErrorsSignal = signal<ReadonlyMap<string, readonly string[]>>(new Map());
    /** Payload errors from the last rejected test run, keyed by canvas node id. */
    public readonly serverErrors: Signal<ReadonlyMap<string, readonly string[]>> = this.serverErrorsSignal.asReadonly();

    public request(nodeType: TestRunNodeType, nodeId: string, payload: TriggerTestPayload): void {
        this.requestsSubject.next({ nodeType, nodeId, payload });
    }

    /** Locks both run buttons; a test run from `nodeId` also drops that node's errors from its previous run. */
    public markRunStarting(nodeId: string | null = null): void {
        this.isRunStartingSignal.set(true);
        this.runningNodeIdSignal.set(nodeId);
        if (nodeId !== null) {
            this.clearServerErrors(nodeId);
        }
    }

    public clearRunStarting(): void {
        this.isRunStartingSignal.set(false);
        this.runningNodeIdSignal.set(null);
    }

    public setServerErrors(nodeId: string, errors: readonly string[]): void {
        this.serverErrorsSignal.update((current) => new Map(current).set(nodeId, errors));
    }

    /** Drops every node's errors, e.g. when another flow loads: they belong to the previous one. */
    public clearAllServerErrors(): void {
        if (this.serverErrorsSignal().size === 0) return;
        this.serverErrorsSignal.set(new Map());
    }

    public clearServerErrors(nodeId: string): void {
        if (!this.serverErrorsSignal().has(nodeId)) return;
        this.serverErrorsSignal.update((current) => {
            const next = new Map(current);
            next.delete(nodeId);
            return next;
        });
    }
}
