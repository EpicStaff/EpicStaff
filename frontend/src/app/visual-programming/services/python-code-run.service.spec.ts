import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ConfigService } from '../../services/config';
import { PollEvent, PythonCodeResult, PythonCodeRunService } from './python-code-run.service';

const SECOND_MS = 1000;
const GRACE_MS = 60_000;

const PENDING: PythonCodeResult = {
    execution_id: 'exec-1',
    status: 'pending',
    result_data: null,
    returncode: null,
    stderr: '',
    stdout: '',
};

describe('PythonCodeRunService result polling deadline', () => {
    let service: PythonCodeRunService;
    let events: PollEvent[];
    let error: Error | null;

    beforeEach(() => {
        vi.useFakeTimers();
        TestBed.configureTestingModule({
            providers: [{ provide: ConfigService, useValue: { apiUrl: '/api/' } }],
        });
        service = TestBed.inject(PythonCodeRunService);
        // The run never finishes: only the deadline can end the wait.
        vi.spyOn(service, 'getResult').mockReturnValue(of(PENDING));
        events = [];
        error = null;
    });

    afterEach(() => vi.useRealTimers());

    function poll(executionTimeoutSeconds: number): void {
        service.pollResultWithEvents('exec-1', executionTimeoutSeconds).subscribe({
            next: (event) => events.push(event),
            error: (failure: Error) => (error = failure),
        });
    }

    it('gives up a grace period after the execution timeout, naming the timeout in seconds', () => {
        poll(90);

        vi.advanceTimersByTime(90 * SECOND_MS + GRACE_MS - 1);
        expect(error).toBeNull();
        expect(events.length).toBeGreaterThan(0);

        vi.advanceTimersByTime(1);
        expect(error?.message).toContain('No result within the execution timeout of 90 s');
    });

    it('waits longer for a code allowed longer', () => {
        poll(600);

        vi.advanceTimersByTime(90 * SECOND_MS + GRACE_MS);
        expect(error).toBeNull();

        vi.advanceTimersByTime(510 * SECOND_MS);
        expect(error?.message).toContain('600 s');
    });

    it('keeps waiting for a timeout too long for a timer, instead of giving up at once', () => {
        poll(2_147_483_647);

        vi.advanceTimersByTime(10 * SECOND_MS);
        expect(error).toBeNull();
    });
});
