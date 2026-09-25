import { FileSizePipe } from '../pipes/file-size.pipe';
import { formatFileSize } from './format-file-size.util';

describe('formatFileSize', () => {
    it.each([
        { bytes: 0, decimalPlaces: 0, expected: '0 B' },
        { bytes: null, decimalPlaces: 0, expected: '0 B' },
        { bytes: undefined, decimalPlaces: 0, expected: '0 B' },
        { bytes: 1023, decimalPlaces: 0, expected: '1023 B' },
        { bytes: 1536, decimalPlaces: 0, expected: '2 KB' },
        { bytes: 1536, decimalPlaces: 2, expected: '1.50 KB' },
        { bytes: 1536, decimalPlaces: 'auto', expected: '2 KB' },
        { bytes: 50 * 1024 * 1024, decimalPlaces: 'auto', expected: '50.0 MB' },
        { bytes: 1610612736, decimalPlaces: 'auto', expected: '1.5 GB' },
        { bytes: 5 * 1024 ** 5, decimalPlaces: 'auto', expected: '5120.0 TB' },
    ] as const)('formats $bytes ($decimalPlaces dp) as "$expected"', ({ bytes, decimalPlaces, expected }) => {
        expect(formatFileSize(bytes, decimalPlaces)).toBe(expected);
    });

    it('is what FileSizePipe shows', () => {
        const pipe = new FileSizePipe();
        for (const bytes of [0, 999, 123456, 987654321]) {
            expect(pipe.transform(bytes, 'auto')).toBe(formatFileSize(bytes, 'auto'));
            expect(pipe.transform(bytes)).toBe(formatFileSize(bytes));
        }
    });
});
