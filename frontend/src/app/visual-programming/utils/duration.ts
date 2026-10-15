const SECONDS_PER_HOUR = 3600;
const SECONDS_PER_MINUTE = 60;

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

/** `3725` → `1 h 2 min 5 s`; `0` → `0 s`. */
export function formatDuration(totalSeconds: number): string {
    const { hours, minutes, seconds } = splitDuration(totalSeconds);
    const parts = [
        hours ? `${hours} h` : '',
        minutes ? `${minutes} min` : '',
        seconds || !totalSeconds ? `${seconds} s` : '',
    ];
    return parts.filter(Boolean).join(' ');
}

/** `3725` → `01:02:05`; hours past 99 keep every digit: `360000` → `100:00:00`. */
export function formatClockDuration(totalSeconds: number): string {
    const { hours, minutes, seconds } = splitDuration(totalSeconds);
    return [hours, minutes, seconds].map((part) => String(part).padStart(2, '0')).join(':');
}

const CLOCK_DURATION_PATTERN = /^(?:(?:(\d+):)?(\d+):)?(\d+)$/;
const LOWER_PART_PATTERN = /^\d{1,2}$/;

/**
 * Reads a duration typed as `hh:mm:ss`, `mm:ss` or a bare number of seconds into total seconds: `01:02:05` → `3725`,
 * `90:00` → `5400`, `600` → `600`. The highest part is unbounded; a part below it must be one or two digits and
 * at most 59. Anything else (a sign, a fraction, an empty part, a number too large to count exactly) → `null`.
 */
export function parseDuration(text: string): number | null {
    const match = CLOCK_DURATION_PATTERN.exec(text.trim());
    if (!match) {
        return null;
    }
    const [, hoursText, minutesText, secondsText] = match;
    const minutesOutOfRange = hoursText !== undefined && !isClockPart(minutesText);
    const secondsOutOfRange = minutesText !== undefined && !isClockPart(secondsText);
    if (minutesOutOfRange || secondsOutOfRange) {
        return null;
    }
    const totalSeconds = joinDuration({
        hours: Number(hoursText ?? 0),
        minutes: Number(minutesText ?? 0),
        seconds: Number(secondsText),
    });
    return Number.isSafeInteger(totalSeconds) ? totalSeconds : null;
}

function isClockPart(text: string): boolean {
    return LOWER_PART_PATTERN.test(text) && Number(text) < 60;
}
