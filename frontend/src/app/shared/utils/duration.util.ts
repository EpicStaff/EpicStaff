const SECONDS_PER_HOUR = 3600;
const SECONDS_PER_MINUTE = 60;
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
 * The digits of `text`, in order, as ASCII: `01:30` → `0130`, `10 min` → `10`, `１５` → `15`. Full-width digits count
 * as digits; every other character is dropped.
 */
export function readDigits(text: string): string {
    return text
        .replace(FULL_WIDTH_DIGIT_PATTERN, (digit) => String.fromCharCode(digit.charCodeAt(0) - FULL_WIDTH_OFFSET))
        .replace(/\D/g, '');
}

/** The total seconds of a `hh:mm:ss` clock: `00:01:30` and `00:00:90` → `90`. */
export function readClockDuration(clock: string): number {
    const [hours, minutes, seconds] = clock.split(':').map(Number);
    return joinDuration({ hours, minutes, seconds });
}

/** `1, 'hour'` → `1 hour`; `2, 'hour'` → `2 hours`. */
function countOf(count: number, unit: string): string {
    return `${count} ${unit}${count === 1 ? '' : 's'}`;
}
