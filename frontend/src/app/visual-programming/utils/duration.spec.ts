import { formatClockDuration, formatDuration, parseDuration } from './duration';

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

describe('parseDuration', () => {
    it('reads hh:mm:ss', () => {
        expect(parseDuration('01:02:05')).toBe(3725);
        expect(parseDuration('00:10:00')).toBe(600);
        expect(parseDuration('1:2:5')).toBe(3725);
    });

    it('reads hours past 99', () => {
        expect(parseDuration('100:00:00')).toBe(360_000);
    });

    it('reads mm:ss, with minutes unbounded as the highest part', () => {
        expect(parseDuration('10:30')).toBe(630);
        expect(parseDuration('90:00')).toBe(5400);
    });

    it('reads a bare number of seconds, unbounded', () => {
        expect(parseDuration('600')).toBe(600);
        expect(parseDuration('0')).toBe(0);
        expect(parseDuration('7200')).toBe(7200);
    });

    it('ignores surrounding whitespace', () => {
        expect(parseDuration('  00:10:00 ')).toBe(600);
    });

    it('refuses minutes or seconds above 59 below a higher part', () => {
        expect(parseDuration('00:60:00')).toBeNull();
        expect(parseDuration('00:00:60')).toBeNull();
        expect(parseDuration('10:60')).toBeNull();
    });

    it('refuses a part below the highest with more than two digits', () => {
        expect(parseDuration('00:010:00')).toBeNull();
        expect(parseDuration('1:005')).toBeNull();
    });

    it.each(['', '   ', 'abc', '10m', '-5', '+5', '1.5', '00:10:0.5', ':10', '10:', '00::00', '1:2:3:4', '1 2'])(
        'refuses %j',
        (text) => {
            expect(parseDuration(text)).toBeNull();
        }
    );

    it('refuses a number too large to count exactly', () => {
        expect(parseDuration('99999999999999999999')).toBeNull();
    });
});
