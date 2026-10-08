import { AgentInstruction } from '../models/agent-definition.model';
import { isInstructionNameTaken, nextDefaultInstructionName, uniqueInstructionName } from './instructions-file.utils';

function named(...names: string[]): AgentInstruction[] {
    return names.map((name) => ({ name, content: '' }));
}

describe('instructions-file utils', () => {
    it('compares names case-insensitively and can skip the row being renamed', () => {
        const list = named('Instruction_1.md', 'Notes.md');
        expect(isInstructionNameTaken('notes.MD', list)).toBe(true);
        expect(isInstructionNameTaken('NOTES.md', list, 1)).toBe(false);
    });

    it('picks the smallest free default name starting after the list length', () => {
        expect(nextDefaultInstructionName([])).toBe('Instruction_1.md');
        expect(nextDefaultInstructionName(named('Instruction_1.md', 'Super_Cool_Instructions.md'))).toBe(
            'Instruction_3.md'
        );
        expect(nextDefaultInstructionName(named('A.md', 'instruction_3.md'))).toBe('Instruction_4.md');
    });

    it('suffixes a taken file name before its extension', () => {
        expect(uniqueInstructionName('cv.md', named('Other.md'))).toBe('cv.md');
        expect(uniqueInstructionName('cv.md', named('CV.md', 'cv_2.md'))).toBe('cv_3.md');
        expect(uniqueInstructionName('README', named('readme'))).toBe('README_2');
    });
});
