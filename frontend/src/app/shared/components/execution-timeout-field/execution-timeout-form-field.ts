import { FormControl } from '@angular/forms';

import { executionTimeoutValidator } from '../../form-validators/execution-timeout.validator';
import { ExecutionTimeoutLimits } from '../../models/execution-timeout-limits.model';

/** The longest timeout the backend can store (a Postgres `integer`): the cap of an edit when there is no maximum. */
export const MAX_STORABLE_SECONDS = 2_147_483_647;

/**
 * The execution timeout of one python code in a form, in seconds, with the limits it was built under.
 *
 * - A code without a timeout shows the backend default, and keeps none until the timeout is edited: the backend
 *   then applies that default. So opening a form never changes the code.
 * - A stored timeout above the maximum (the maximum was lowered after it was saved) stays valid: the backend saves
 *   it as the maximum, and the field says so. An edit above the maximum (or, without one, above what the backend
 *   can store) is capped at it.
 */
export class ExecutionTimeoutFormField {
    public readonly control: FormControl<number>;
    private edited = false;

    constructor(
        private readonly storedSeconds: number | undefined,
        public readonly limits: ExecutionTimeoutLimits
    ) {
        this.control = new FormControl(storedSeconds ?? limits.defaultSeconds, {
            nonNullable: true,
            validators: executionTimeoutValidator(limits.minSeconds),
        });
    }

    /** The timeout to keep on the python code. */
    public get value(): number | undefined {
        return this.edited ? this.control.value : this.storedSeconds;
    }

    /** The most an edit keeps: the maximum, or without one what the backend can store. */
    public get upperBound(): number {
        return this.limits.maxSeconds ?? MAX_STORABLE_SECONDS;
    }

    public edit(seconds: number): void {
        // Before `setValue`: the panel reads `value` when the control reports the change.
        this.edited = true;
        this.control.markAsDirty();
        this.control.setValue(this.capped(seconds));
    }

    /**
     * Edits the timeout by `deltaSeconds`, landing within the limits: never below the minimum, never above the upper
     * bound. So a step from a stored timeout outside them (below the minimum, above a lowered maximum) brings it in.
     */
    public step(deltaSeconds: number): void {
        this.edit(Math.max(this.limits.minSeconds, this.capped(this.control.value + deltaSeconds)));
    }

    /** What an edit to `seconds` keeps: capped at the upper bound. */
    public capped(seconds: number): number {
        return Math.min(seconds, this.upperBound);
    }
}
