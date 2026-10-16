import { FormControl } from '@angular/forms';

import { ExecutionTimeoutLimits } from '../../../../core/models/execution-timeout-limits.model';
import { executionTimeoutValidator } from '../../../../utils/validation/execution-timeout.validator';

/** The longest timeout the backend can store (a Postgres `integer`): the cap of an edit when there is no maximum. */
export const MAX_STORABLE_SECONDS = 2_147_483_647;

/**
 * The execution timeout of one python code in a panel form, in seconds, with the limits it was built under.
 *
 * - A code without a timeout shows the backend default, and keeps none until the timeout is edited: the backend
 *   then applies that default. So opening a panel never changes a node.
 * - A stored timeout above the maximum (the maximum was lowered after it was saved) stays valid: the backend saves
 *   it as the maximum, and the field warns about it. An edit above the maximum (or, without one, above what the
 *   backend can store) is capped at it.
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

    public edit(seconds: number): void {
        // Before `setValue`: the panel reads `value` when the control reports the change.
        this.edited = true;
        this.control.markAsDirty();
        this.control.setValue(this.capped(seconds));
    }

    /** What an edit to `seconds` keeps: capped at the maximum, or without one at what the backend can store. */
    public capped(seconds: number): number {
        return Math.min(seconds, this.limits.maxSeconds ?? MAX_STORABLE_SECONDS);
    }
}
