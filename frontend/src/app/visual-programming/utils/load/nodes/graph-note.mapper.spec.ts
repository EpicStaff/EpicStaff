import { NOTE_COLORS } from '../../../core/utils/note-colors.util';
import { liveNote } from '../../testing/live-graph.fixture';
import { mapGraphNoteToModel } from './graph-note.mapper';

function loadColor(backgroundColor: unknown): string | undefined {
    return mapGraphNoteToModel({ ...liveNote, metadata: { backgroundColor } }).data.backgroundColor;
}

describe('mapGraphNoteToModel background colour', () => {
    it.each(NOTE_COLORS)('keeps the palette colour %s', (color) => {
        expect(loadColor(color)).toBe(color);
    });

    it('keeps a lower-case hex colour written by an older picker', () => {
        expect(loadColor('#ffef9f')).toBe('#ffef9f');
    });

    // The colour is drawn as a CSS value; a stored or imported non-hex value must not reach the canvas.
    it.each([
        'url(https://attacker.example/pixel.png)',
        'red; background:url(https://attacker.example/pixel.png)',
        '#ffffd1 url(https://attacker.example/pixel.png)',
        'expression(alert(1))',
        'red',
        '#fff',
        '#ffffd1ff',
        '',
        null,
        42,
    ])('drops %j so the note falls back to the default colour', (stored) => {
        expect(loadColor(stored)).toBeUndefined();
    });

    it('leaves a note with no stored colour on the default colour', () => {
        expect(mapGraphNoteToModel({ ...liveNote, metadata: {} }).data.backgroundColor).toBeUndefined();
    });
});
