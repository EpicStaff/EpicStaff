/** A place on the forecast page. */
export interface Place {
    slug: string;
    name: string;
    temperatureCelsius: number;
    summary: string;
}

/**
 * Fixed sample data: this first version has no backend, so it makes no network calls besides the platform config.
 * Later versions fetch real forecasts through the plugin's own backend.
 */
export const SAMPLE_PLACES: readonly Place[] = [
    { slug: 'berlin', name: 'Berlin', temperatureCelsius: 14, summary: 'Light rain in the afternoon' },
    { slug: 'kyiv', name: 'Kyiv', temperatureCelsius: 11, summary: 'Cloudy, dry' },
    { slug: 'lisbon', name: 'Lisbon', temperatureCelsius: 21, summary: 'Sunny' },
];
