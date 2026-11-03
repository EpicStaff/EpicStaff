import { TourContent } from '../../model/tour-content';
import { TourProgress } from '../tour-renderer';
import { tourAnnouncement } from './tour-announcement';

describe('tourAnnouncement', () => {
    it.each<[description: string, content: TourContent, progress: TourProgress | null, expected: string]>([
        [
            'reads the progress, title and text as sentences',
            { title: 'Middle', body: ['Look here.'] },
            { current: 1, total: 2 },
            'Step 1 of 2. Middle. Look here.',
        ],
        ['leaves out progress the step does not show', { title: 'Welcome', body: [] }, null, 'Welcome.'],
        [
            'joins the runs of a formatted paragraph',
            {
                title: 'One more step',
                body: [[{ text: 'Click ' }, { text: 'Update', strong: true }, { text: ' now' }]],
            },
            null,
            'One more step. Click Update now.',
        ],
        [
            'keeps the punctuation that already ends a sentence',
            { title: 'Welcome to Quick Start!', body: ['Ready?', 'Go…'] },
            null,
            'Welcome to Quick Start! Ready? Go…',
        ],
    ])('%s', (_description, content, progress, expected) => {
        expect(tourAnnouncement(content, progress)).toBe(expected);
    });
});
