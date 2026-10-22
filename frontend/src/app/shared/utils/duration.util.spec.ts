import { formatClockDuration, formatDurationInWords, readClockDuration, readDigits } from './duration.util';

describe('formatClockDuration', () => {
    it('pads every part to two digits', () => {
        expect(formatClockDuration(0)).toBe('00:00:00');
        expect(formatClockDuration(600)).toBe('00:10:00');
        expect(formatClockDuration(3725)).toBe('01:02:05');
    });

    it('keeps every digit of hours past 99', () => {
        expect(formatClockDuration(100 * 3600 + 61)).toBe('100:01:01');
    });
});

describe('formatDurationInWords', () => {
    it('names only the parts that are set, in words', () => {
        expect(formatDurationInWords(3)).toBe('3 seconds');
        expect(formatDurationInWords(90)).toBe('1 minute 30 seconds');
        expect(formatDurationInWords(24 * 3600)).toBe('24 hours');
        expect(formatDurationInWords(2 * 3600 + 5)).toBe('2 hours 5 seconds');
    });

    it('names a single unit in the singular', () => {
        expect(formatDurationInWords(3661)).toBe('1 hour 1 minute 1 second');
    });

    it('names zero in seconds', () => {
        expect(formatDurationInWords(0)).toBe('0 seconds');
    });
});

describe('readDigits', () => {
    it('keeps the digits in order, dropping every other character', () => {
        expect(readDigits('01:30:00')).toBe('013000');
        expect(readDigits('10 min')).toBe('10');
        expect(readDigits('-1.5')).toBe('15');
        expect(readDigits('abc')).toBe('');
    });

    it('reads full-width digits as ASCII', () => {
        expect(readDigits('０１:３０')).toBe('0130');
    });
});

describe('readClockDuration', () => {
    it('counts every part, even minutes or seconds above 59', () => {
        expect(readClockDuration('01:02:05')).toBe(3725);
        expect(readClockDuration('00:00:90')).toBe(90);
        expect(readClockDuration('00:01:30')).toBe(90);
        expect(readClockDuration('100:00:00')).toBe(360_000);
    });
});
