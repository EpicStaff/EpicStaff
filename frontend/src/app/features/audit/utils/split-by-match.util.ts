export interface MatchSegment {
    text: string;
    isMatch: boolean;
}

export function splitByMatch(text: string, term: string): MatchSegment[] {
    const needle = term.trim().toLowerCase();
    if (needle === '') {
        return [{ text, isMatch: false }];
    }

    const haystack = text.toLowerCase();
    const segments: MatchSegment[] = [];
    let cursor = 0;
    let index = haystack.indexOf(needle);
    while (index !== -1) {
        if (index > cursor) {
            segments.push({ text: text.slice(cursor, index), isMatch: false });
        }
        segments.push({ text: text.slice(index, index + needle.length), isMatch: true });
        cursor = index + needle.length;
        index = haystack.indexOf(needle, cursor);
    }
    if (cursor < text.length) {
        segments.push({ text: text.slice(cursor), isMatch: false });
    }
    return segments;
}
