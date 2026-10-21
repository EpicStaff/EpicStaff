const SECONDS_PER_HOUR = 3600;
const SECONDS_PER_MINUTE = 60;
/** The digits of `00:00:00`. */
const CLOCK_DIGITS = 6;
const FULL_WIDTH_DIGIT_PATTERN = /[\uFF10-\uFF19]/g;
/** From a full-width digit (`０` is U+FF10) to its ASCII one (`0` is U+0030). */
const FULL_WIDTH_OFFSET = 0xff10 - 0x30;

export interface DurationParts {
    hours: number;
    minutes: number;
    seconds: number;
}

/** `3725` → `{ hours: 1, minutes: 2, seconds: 5 }`. */
export function splitDuration(totalSeconds: number): DurationParts {
    return {
        hours: Math.floor(totalSeconds / SECONDS_PER_HOUR),
        minutes: Math.floor((totalSeconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE),
        seconds: totalSeconds % SECONDS_PER_MINUTE,
    };
}

/** The inverse of `splitDuration`. */
export function joinDuration({ hours, minutes, seconds }: DurationParts): number {
    return hours * SECONDS_PER_HOUR + minutes * SECONDS_PER_MINUTE + seconds;
}

/**
 * The duration in words, for a sentence: `3` → `3 seconds`, `90` → `1 minute 30 seconds`, `86400` → `24 hours`,
 * `3661` → `1 hour 1 minute 1 second`; `0` → `0 seconds`. Only the parts that are set are named.
 */
export function formatDurationInWords(totalSeconds: number): string {
    const { hours, minutes, seconds } = splitDuration(totalSeconds);
    const parts = [
        hours ? countOf(hours, 'hour') : '',
        minutes ? countOf(minutes, 'minute') : '',
        seconds || !totalSeconds ? countOf(seconds, 'second') : '',
    ];
    return parts.filter(Boolean).join(' ');
}

/** `3725` → `01:02:05`; hours past 99 keep every digit: `360000` → `100:00:00`. */
export function formatClockDuration(totalSeconds: number): string {
    const { hours, minutes, seconds } = splitDuration(totalSeconds);
    return [hours, minutes, seconds].map((part) => String(part).padStart(2, '0')).join(':');
}

/**
 * The digits of `text` as a clock, filled from the right like a microwave timer: `1500` → `00:15:00`,
 * `01:30:000` → `13:00:00`, `10 min` → `00:00:10`, `` → `00:00:00`. Full-width digits (`１５`) count as digits;
 * every other character is dropped, and so are leading zeros beyond the six digits of `00:00:00`. Only the first
 * `maxDigits` of the remaining digits are kept: one typed at the end past the limit is dropped.
 * Minutes and seconds keep what was typed, even above 59 (`00:00:90`): `readClockDuration` still counts them.
 */
export function maskClockDuration(text: string, maxDigits: number): string {
    const digits = text
        .replace(FULL_WIDTH_DIGIT_PATTERN, (digit) => String.fromCharCode(digit.charCodeAt(0) - FULL_WIDTH_OFFSET))
        .replace(/\D/g, '')
        .replace(/^0+/, '')
        .slice(0, maxDigits)
        .padStart(CLOCK_DIGITS, '0');
    return `${digits.slice(0, -4)}:${digits.slice(-4, -2)}:${digits.slice(-2)}`;
}

/** The total seconds of a clock `maskClockDuration` wrote: `00:01:30` and `00:00:90` → `90`. */
export function readClockDuration(clock: string): number {
    const [hours, minutes, seconds] = clock.split(':').map(Number);
    return joinDuration({ hours, minutes, seconds });
}

/** `1, 'hour'` → `1 hour`; `2, 'hour'` → `2 hours`. */
function countOf(count: number, unit: string): string {
    return `${count} ${unit}${count === 1 ? '' : 's'}`;
}
