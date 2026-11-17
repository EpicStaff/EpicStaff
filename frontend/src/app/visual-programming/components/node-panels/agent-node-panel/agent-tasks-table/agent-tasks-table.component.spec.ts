import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ToastService } from '../../../../../services/notifications';
import { AgentNodeTaskUi } from '../../../../core/models/agent-node.model';
import { NodeSaveErrorsStore } from '../../../../services/node-save-errors.store';
import { AgentTasksTableComponent } from './agent-tasks-table.component';

function task(tempId: string, instructions: string): AgentNodeTaskUi {
    return { tempId, name: tempId, instructions, output_schema: {}, contextRefs: [] };
}

function createTable(tasks: AgentNodeTaskUi[]): ComponentFixture<AgentTasksTableComponent> {
    TestBed.configureTestingModule({ providers: [{ provide: ToastService, useValue: { warning: vi.fn() } }] });
    const fixture = TestBed.createComponent(AgentTasksTableComponent);
    fixture.componentRef.setInput('tasks', tasks);
    fixture.detectChanges();
    return fixture;
}

function instructionsTextareas(fixture: ComponentFixture<AgentTasksTableComponent>): HTMLTextAreaElement[] {
    return Array.from(
        (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLTextAreaElement>('.att-cell--instructions textarea')
    );
}

describe('AgentTasksTableComponent instructions a save refused', () => {
    const REFUSED = "Placeholder '{topic!r}' is not allowed.";

    function shownSaveErrors(fixture: ComponentFixture<AgentTasksTableComponent>): string[] {
        return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('app-node-save-errors li')).map(
            (item) => item.textContent!.trim()
        );
    }

    function outlinedRows(fixture: ComponentFixture<AgentTasksTableComponent>): number[] {
        return Array.from(
            (fixture.nativeElement as HTMLElement).querySelectorAll('.att-cell--instructions .att-textarea-highlight')
        ).flatMap((cell, index) => (cell.classList.contains('att-textarea-highlight--invalid') ? [index] : []));
    }

    it('outlines the task and says why under the table, until its instructions are edited', () => {
        const fixture = createTable([task('a', 'Fine'), task('b', 'Say {topic!r}')]);
        // As the agent panel binds it: the table's edits come back as its tasks.
        fixture.componentInstance.tasksChange.subscribe((tasks) => fixture.componentRef.setInput('tasks', tasks));
        TestBed.inject(NodeSaveErrorsStore).setAll(
            new Map([
                [
                    'agent-1',
                    [
                        {
                            field: 'instructions',
                            child: { list: 'tasks', key: 'b', position: 1 },
                            sentValue: 'Say {topic!r}',
                            messages: [REFUSED],
                        },
                    ],
                ],
            ])
        );
        fixture.componentRef.setInput('nodeId', 'agent-1');
        fixture.detectChanges();

        expect(shownSaveErrors(fixture)).toEqual([`Task 2 instructions: ${REFUSED}`]);
        expect(outlinedRows(fixture)).toEqual([1]);

        const refusedTextarea = instructionsTextareas(fixture)[1];
        refusedTextarea.value = 'Say {topic}';
        refusedTextarea.dispatchEvent(new Event('input'));
        fixture.detectChanges();

        expect(shownSaveErrors(fixture)).toEqual([]);
        expect(outlinedRows(fixture)).toEqual([]);
    });
});

describe('AgentTasksTableComponent instructions focus', () => {
    it('emits the index of the row whose instructions cell was focused', () => {
        const fixture = createTable([task('a', 'first'), task('b', 'second')]);
        const focused: number[] = [];
        fixture.componentInstance.instructionsFocus.subscribe((index) => focused.push(index));

        instructionsTextareas(fixture)[1].focus();

        expect(focused).toEqual([1]);
    });

    it('does not expand the panel when an instructions cell is focused', () => {
        const fixture = createTable([task('a', 'first')]);
        const selections: unknown[] = [];
        fixture.componentInstance.cellSelect.subscribe((selection) => selections.push(selection));

        instructionsTextareas(fixture)[0].focus();

        expect(selections).toEqual([]);
    });

    it('emits cellSelect, and no instructionsFocus, when the expand icon is clicked', () => {
        const fixture = createTable([task('a', 'first'), task('b', 'second')]);
        const selections: unknown[] = [];
        const focused: number[] = [];
        fixture.componentInstance.cellSelect.subscribe((selection) => selections.push(selection));
        fixture.componentInstance.instructionsFocus.subscribe((index) => focused.push(index));

        const icons = (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>(
            '.att-cell--instructions .att-expand-icon'
        );
        icons[1].click();

        expect(selections).toEqual([{ taskIndex: 1, field: 'instructions' }]);
        expect(focused).toEqual([]);
    });

    it('inserts the variable at the caret of the requested row only', () => {
        const fixture = createTable([task('a', 'first'), task('b', 'say  now')]);
        const emitted: AgentNodeTaskUi[][] = [];
        fixture.componentInstance.tasksChange.subscribe((tasks) => emitted.push(tasks));
        const secondTextarea = instructionsTextareas(fixture)[1];
        secondTextarea.focus();
        secondTextarea.setSelectionRange(4, 4);

        fixture.componentInstance.insertIntoInstructionsAtCursor(1, 'topic');

        expect(emitted).toHaveLength(1);
        expect(emitted[0].map((row) => row.instructions)).toEqual(['first', 'say {topic} now']);
    });
});
