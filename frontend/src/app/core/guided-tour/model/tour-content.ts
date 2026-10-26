/** A piece of a paragraph. Text only: tour copy is rendered through templates, never as HTML. */
export interface TourTextRun {
    readonly text: string;
    readonly strong?: boolean;
}

/** Plain text, or text runs when part of it is emphasised. */
export type TourParagraph = string | readonly TourTextRun[];

/** A decorative image above the title. Width and height reserve its space before it loads. */
export interface TourMedia {
    readonly src: string;
    readonly width: number;
    readonly height: number;
}

export interface TourContent {
    readonly title: string;
    /** An `app-svg-icon` sprite id shown before the title; decorative. */
    readonly titleIcon?: string;
    readonly body: readonly TourParagraph[];
    readonly media?: TourMedia;
}

/** The side of the target the popover prefers; it flips to another side when there is no room. */
export type TourSide = 'top' | 'bottom' | 'left' | 'right';

/** Where the popover goes when the step has no target, or its target is not visible. */
export type TourFloatingPosition = 'center' | 'bottom-start';
