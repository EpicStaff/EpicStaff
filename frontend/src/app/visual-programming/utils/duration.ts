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
