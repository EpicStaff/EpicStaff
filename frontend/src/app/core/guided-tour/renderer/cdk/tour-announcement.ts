import { TourContent, TourParagraph } from '../../model/tour-content';
import { TourProgress } from '../tour-renderer';

/** What a screen reader hears when a step starts while the focus stays on the page: progress, title and text. */
export function tourAnnouncement(content: TourContent, progress: TourProgress | null): string {
    const texts = [content.title, ...content.body.map(paragraphText)];
    if (progress) {
        texts.unshift(`Step ${progress.current} of ${progress.total}`);
    }
    return texts.map(asSentence).join(' ');
}

function paragraphText(paragraph: TourParagraph): string {
    return typeof paragraph === 'string' ? paragraph : paragraph.map((run) => run.text).join('');
}

/** Ends `text` with a full stop unless it already ends a sentence, so a screen reader pauses between the parts. */
function asSentence(text: string): string {
    const trimmed = text.trim();
    return /[.!?…]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}
