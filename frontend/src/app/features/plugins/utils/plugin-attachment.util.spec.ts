import { attachmentFileName } from './plugin-attachment.util';

describe('attachmentFileName', () => {
    it('reads the quoted file name of an attachment', () => {
        expect(attachmentFileName('attachment; filename="weather-development-runtime.json"')).toBe(
            'weather-development-runtime.json'
        );
    });

    it('reads an unquoted file name', () => {
        expect(attachmentFileName('attachment; filename=weather.json')).toBe('weather.json');
    });

    it.each([
        null,
        '',
        'attachment',
        'attachment; filename="../weather.json"',
        'attachment; filename="dir/weather.json"',
        'attachment; filename=".weather.json"',
        "attachment; filename*=UTF-8''weather.json",
    ])('gives null for %j', (header) => {
        expect(attachmentFileName(header)).toBeNull();
    });
});
