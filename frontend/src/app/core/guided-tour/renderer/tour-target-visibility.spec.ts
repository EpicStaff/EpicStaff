import { isTourTargetVisible } from './tour-target-visibility';

interface TargetOptions {
    readonly connected?: boolean;
    readonly inert?: boolean;
    readonly visible?: boolean;
    readonly width?: number;
}

describe('isTourTargetVisible', () => {
    let page: HTMLElement;

    beforeEach(() => {
        page = document.createElement('div');
        document.body.appendChild(page);
    });
    afterEach(() => page.remove());

    /** An element in a container, with the box and visibility jsdom cannot compute. */
    function target(options: TargetOptions = {}): Element {
        const container = document.createElement('div');
        if (options.inert) {
            container.setAttribute('inert', '');
        }
        const element = document.createElement('a');
        container.appendChild(element);
        if (options.connected ?? true) {
            page.appendChild(container);
        }
        const width = options.width ?? 120;
        Object.assign(element, {
            getBoundingClientRect: () => ({ top: 100, left: 40, width, height: width > 0 ? 32 : 0 }),
            checkVisibility: () => options.visible ?? true,
        });
        return element;
    }

    it.each<[description: string, options: TargetOptions, expected: boolean]>([
        ['counts a laid-out element on the page', {}, true],
        ['rejects an element no longer in the document', { connected: false }, false],
        ['rejects an element in an inert subtree (behind an open drawer)', { inert: true }, false],
        ['rejects an element hidden by visibility (a closed drawer)', { visible: false }, false],
        ['rejects an element without a box', { width: 0 }, false],
    ])('%s', (_description, options, expected) => {
        expect(isTourTargetVisible(target(options))).toBe(expected);
    });
});
