import { formatClockDuration, formatDuration, maskClockDuration, readClockDuration } from './duration';

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

describe('formatDuration', () => {
    it('names only the parts that are set', () => {
        expect(formatDuration(3725)).toBe('1 h 2 min 5 s');
        expect(formatDuration(3600)).toBe('1 h');
        expect(formatDuration(0)).toBe('0 s');
    });
});

describe('maskClockDuration', () => {
    const mask = (text: string): string => maskClockDuration(text, 9);

    it('fills the digits from the right, like a microwave timer', () => {
        expect(mask('5')).toBe('00:00:05');
        expect(mask('1500')).toBe('00:15:00');
        expect(mask('13000')).toBe('01:30:00');
    });

    it('shifts a digit typed after a clock in from the right', () => {
        expect(mask('00:10:005')).toBe('01:00:05');
    });

    it('shifts the clock right when its last digit is deleted', () => {
        expect(mask('00:10:0')).toBe('00:01:00');
    });

    it('reads a pasted clock as it is', () => {
        expect(mask('01:30:00')).toBe('01:30:00');
    });

    it('drops every character but digits', () => {
        expect(mask('10 min')).toBe('00:00:10');
        expect(mask('-1.5')).toBe('00:00:15');
        expect(mask('')).toBe('00:00:00');
        expect(mask('abc')).toBe('00:00:00');
    });

    it('keeps minutes and seconds above 59 as typed', () => {
        expect(mask('90')).toBe('00:00:90');
    });

    it('keeps more than two hour digits, without extra leading zeros', () => {
        expect(mask('1000000')).toBe('100:00:00');
        expect(mask('000000100:00:00')).toBe('100:00:00');
    });

    it('reads full-width digits', () => {
        expect(mask('１５００')).toBe('00:15:00');
        expect(mask('０１:３０:００')).toBe('01:30:00');
    });

    it('keeps the first digits up to the limit, dropping one typed at the end past it', () => {
        expect(mask('1234567890')).toBe('12345:67:89');
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
