/** Legacy IANA names some browsers and stored data still use, mapped to the current name. */
export const IANA_ALIASES: Readonly<Record<string, string>> = {
    'Europe/Kiev': 'Europe/Kyiv',
};

export function normalizeIana(zone: string): string {
    return IANA_ALIASES[zone] ?? zone;
}

/** The browser's own zone, under its current IANA name. */
export function browserTimeZone(): string {
    return normalizeIana(Intl.DateTimeFormat().resolvedOptions().timeZone);
}

/** The zone a timezone preference stands for: the chosen zone, or the browser's while none is chosen. */
export function effectiveZone(preference: string | null): string {
    return preference ? normalizeIana(preference) : browserTimeZone();
}
