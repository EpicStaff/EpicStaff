import { TestBed } from '@angular/core/testing';

import { MessageType, PythonCodeExecutionData } from '../../../../models/graph-session-message.model';
import { PythonMessageComponent } from './python-message.component';

/** `error` is the sentence crew says the node failed with; older messages have none. */
function render(executionData: PythonCodeExecutionData, error?: string): HTMLElement {
    const fixture = TestBed.createComponent(PythonMessageComponent);
    fixture.componentRef.setInput('message', {
        id: 1,
        session: 1,
        name: 'Python #1 #4',
        execution_order: 1,
        created_at: '2026-11-04T00:00:00Z',
        metadata: {},
        message_data: { message_type: MessageType.PYTHON, python_code_execution_data: executionData, error },
    });
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

function sectionText(element: HTMLElement, container: string): string | null {
    return element.querySelector(`.${container} pre`)?.textContent ?? null;
}

function sectionTitles(element: HTMLElement): string[] {
    return Array.from(element.querySelectorAll('.section-heading'), (heading) => heading.textContent?.trim() ?? '');
}

describe('PythonMessageComponent', () => {
    it('shows what a failed run wrote to stderr in the Error section', () => {
        const element = render({
            execution_id: 'run-1',
            result_data: null,
            stdout: '',
            stderr: 'Traceback (most recent call last):\n  ValueError: bad input\n',
            returncode: 1,
        });

        expect(sectionTitles(element)).toContain('Error');
        expect(sectionTitles(element)).not.toContain('Log');
        expect(sectionText(element, 'stderr-container')).toBe(
            'Traceback (most recent call last):\n  ValueError: bad input'
        );
        expect(element.querySelector('.stderr-container .error-content')).not.toBeNull();
        expect(element.querySelector('.output-container')).toBeNull();
    });

    it("shows the node's own sentence as the Error, and stderr that says more as a neutral Log", () => {
        const sentence = 'Input "y" isn\'t a parameter of main(). Add it to main, or remove it from the input map.';
        const element = render(
            {
                execution_id: 'run-4',
                result_data: null,
                stdout: '',
                stderr: "loading\nTypeError: main() got an unexpected keyword argument 'y'\n",
                returncode: 1,
            },
            sentence
        );

        expect(sectionTitles(element)).toEqual(expect.arrayContaining(['Error', 'Log']));
        expect(sectionText(element, 'error-container')).toBe(sentence);
        expect(sectionText(element, 'stderr-container')).toBe(
            "loading\nTypeError: main() got an unexpected keyword argument 'y'"
        );
        expect(element.querySelector('.stderr-container .error-content')).toBeNull();
    });

    it('shows the error once when stderr says no more than the sentence', () => {
        const sentence = "NameError on line 4: name 'file_pat' is not defined";
        const element = render(
            { execution_id: 'run-5', result_data: null, stdout: '', stderr: `${sentence}\n`, returncode: 1 },
            sentence
        );

        expect(sectionTitles(element).filter((title) => title === 'Error' || title === 'Log')).toEqual(['Error']);
        expect(sectionText(element, 'error-container')).toBe(sentence);
        expect(element.querySelector('.stderr-container')).toBeNull();
    });

    it('shows what a successful run wrote to stderr in a neutral Log section, not as an Error', () => {
        const element = render({
            execution_id: 'run-3',
            result_data: '{"total": 3}',
            stdout: '',
            stderr: 'WARNING: using the default limit\n',
            returncode: 0,
        });

        expect(sectionTitles(element)).toContain('Log');
        expect(sectionTitles(element)).not.toContain('Error');
        expect(sectionText(element, 'stderr-container')).toBe('WARNING: using the default limit');
        expect(element.querySelector('.stderr-container .error-content')).toBeNull();
    });

    it('shows the returned value in the Output section, and no Error or Log section for a clean run', () => {
        const element = render({
            execution_id: 'run-2',
            result_data: '{"total": 3}',
            stdout: 'counting\n',
            stderr: '',
            returncode: 0,
        });

        expect(sectionText(element, 'output-container')).toBe('{\n  "total": 3\n}');
        expect(element.querySelector('.stderr-container')).toBeNull();
    });
});
