import { TestBed } from '@angular/core/testing';

import { MessageType, PythonCodeExecutionData } from '../../../../models/graph-session-message.model';
import { PythonMessageComponent } from './python-message.component';

function render(executionData: PythonCodeExecutionData): HTMLElement {
    const fixture = TestBed.createComponent(PythonMessageComponent);
    fixture.componentRef.setInput('message', {
        id: 1,
        session: 1,
        name: 'Python #1 #4',
        execution_order: 1,
        created_at: '2026-11-04T00:00:00Z',
        metadata: {},
        message_data: { message_type: MessageType.PYTHON, python_code_execution_data: executionData },
    });
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

function sectionText(element: HTMLElement, container: string): string | null {
    return element.querySelector(`.${container} pre`)?.textContent ?? null;
}

describe('PythonMessageComponent', () => {
    it('shows what the code wrote to stderr in the Error section', () => {
        const element = render({
            execution_id: 'run-1',
            result_data: null,
            stdout: '',
            stderr: 'Traceback (most recent call last):\n  ValueError: bad input\n',
            returncode: 1,
        });

        expect(sectionText(element, 'error-container')).toBe(
            'Traceback (most recent call last):\n  ValueError: bad input'
        );
        expect(element.querySelector('.output-container')).toBeNull();
    });

    it('shows the returned value in the Output section, and no Error section for a clean run', () => {
        const element = render({
            execution_id: 'run-2',
            result_data: '{"total": 3}',
            stdout: 'counting\n',
            stderr: '',
            returncode: 0,
        });

        expect(sectionText(element, 'output-container')).toBe('{\n  "total": 3\n}');
        expect(element.querySelector('.error-container')).toBeNull();
    });
});
