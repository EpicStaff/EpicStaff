import { ScheduleTriggerNodeData } from '../models/schedule-trigger.model';
import { defaultScheduleStartDateTime, generateScheduleName } from './schedule-trigger-defaults.util';

describe('defaultScheduleStartDateTime', () => {
    // Local wall-clock dates: the default start follows the browser clock.
    it.each([
        ['just after the hour', new Date(2026, 9, 23, 13, 1, 45), '2026-10-23T13:30:00'],
        ['just before the half hour', new Date(2026, 9, 23, 13, 29, 59), '2026-10-23T13:30:00'],
        ['exactly on the hour', new Date(2026, 9, 23, 13, 0, 0), '2026-10-23T13:30:00'],
        ['exactly on the half hour', new Date(2026, 9, 23, 13, 30, 0), '2026-10-23T14:00:00'],
        ['past the half hour', new Date(2026, 9, 23, 13, 31, 0), '2026-10-23T14:00:00'],
        ['late on the last day of the year', new Date(2026, 11, 31, 23, 50, 12), '2027-01-01T00:00:00'],
        ['late on the last day of a month', new Date(2026, 1, 28, 23, 45, 0), '2026-03-01T00:00:00'],
    ])('rounds a clock %s up to the next :00 or :30', (_case, now, expected) => {
        expect(defaultScheduleStartDateTime(now)).toBe(expected);
    });
});

describe('generateScheduleName', () => {
    const once: ScheduleTriggerNodeData = {
        isActive: false,
        runMode: 'once',
        startDateTime: '2026-10-23T13:00:00',
        intervalEvery: null,
        intervalUnit: null,
        weekdays: [],
        endType: 'never',
        endDateTime: null,
        maxRuns: null,
        timezone: 'Europe/Kyiv',
    };
    const repeat: ScheduleTriggerNodeData = { ...once, runMode: 'repeat', intervalEvery: 1, intervalUnit: 'hours' };

    it.each<[string, ScheduleTriggerNodeData, string]>([
        ['a one-time run', once, 'Once on 23 Oct 2026 at 13-00'],
        [
            'a one-time run on a single-digit day',
            { ...once, startDateTime: '2026-01-05T09:30:00' },
            'Once on 05 Jan 2026 at 09-30',
        ],
        ['a one-time run with no start yet', { ...once, startDateTime: '' }, 'One-time schedule'],
        ['every hour', repeat, 'Every hour'],
        ['every 15 minutes', { ...repeat, intervalEvery: 15, intervalUnit: 'minutes' }, 'Every 15 minutes'],
        [
            'weekly on up to three days, in week order',
            { ...repeat, intervalUnit: 'weeks', weekdays: ['fri', 'mon'] },
            'Every week on Mon, Fri',
        ],
        [
            'weekly on more than three days',
            { ...repeat, intervalUnit: 'weeks', weekdays: ['mon', 'tue', 'wed', 'thu'] },
            'Every week on selected days',
        ],
        [
            'until a date',
            { ...repeat, intervalUnit: 'days', endType: 'on_date', endDateTime: '2026-12-31T00:00:00' },
            'Every day until 31 Dec 2026',
        ],
        ['for one run', { ...repeat, endType: 'after_n_runs', maxRuns: 1 }, 'Every hour for 1 run'],
        ['for several runs', { ...repeat, endType: 'after_n_runs', maxRuns: 5 }, 'Every hour for 5 runs'],
    ])('names %s', (_case, data, expected) => {
        expect(generateScheduleName(data)).toBe(expected);
    });
});
