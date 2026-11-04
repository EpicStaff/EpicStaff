import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ToastService } from '../../../../../services/notifications';
import { AgentNodeTaskUi } from '../../../../core/models/agent-node.model';
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
