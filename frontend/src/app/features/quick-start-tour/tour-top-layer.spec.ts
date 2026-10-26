import type { DriverHook, DriveStep } from 'driver.js';

import { TourTopLayer, withTopLayer } from './tour-top-layer';

type HookOptions = Parameters<DriverHook>[2];

describe('TourTopLayer', () => {
    // Before and after: other spec files share this jsdom document.
    const removeTourElements = (): void => {
        document.body
            .querySelectorAll('.driver-overlay, .driver-popover, .quickstart-tour-layer')
            .forEach((element) => {
                element.remove();
            });
    };
    beforeEach(removeTourElements);
    afterEach(removeTourElements);

    // A raised layer listens for keydown on the document until disposed; dispose every layer a test created.
    const layers: TourTopLayer[] = [];
    afterEach(() => layers.splice(0).forEach((layer) => layer.dispose()));

    function createLayer(): TourTopLayer {
        const layer = new TourTopLayer(document);
        layers.push(layer);
        return layer;
    }

    function appendToBody(className: string): HTMLElement {
        const element = document.createElement('div');
        element.className = className;
        document.body.appendChild(element);
        return element;
    }

    it('moves the driver.js overlay and popover from <body> into a manual popover host', () => {
        const overlay = appendToBody('driver-overlay');
        const popover = appendToBody('driver-popover');
        const layer = createLayer();

        layer.raise();

        const host = document.querySelector('.quickstart-tour-layer');
        expect(host?.getAttribute('popover')).toBe('manual');
        expect(overlay.parentElement).toBe(host);
        expect(popover.parentElement).toBe(host);
    });

    it('reuses one host and picks up a popover re-created for the next step', () => {
        const layer = createLayer();
        appendToBody('driver-popover');
        layer.raise();

        const nextPopover = appendToBody('driver-popover');
        layer.raise();

        expect(document.querySelectorAll('.quickstart-tour-layer')).toHaveLength(1);
        expect(nextPopover.parentElement?.classList.contains('quickstart-tour-layer')).toBe(true);
    });

    it('removes the host on dispose, and dispose is idempotent', () => {
        const layer = createLayer();
        layer.raise();

        layer.dispose();
        layer.dispose();

        expect(document.querySelector('.quickstart-tour-layer')).toBeNull();
    });

    it('raises the layer from every step hook and still runs the step’s own hooks', () => {
        const layer = createLayer();
        const raise = vi.spyOn(layer, 'raise');
        const ownHighlighted = vi.fn();
        const ownPopoverRender = vi.fn();
        const [step] = withTopLayer(
            [{ onHighlighted: ownHighlighted, popover: { onPopoverRender: ownPopoverRender } } as DriveStep],
            layer
        );
        const options = {} as HookOptions;

        step.onHighlightStarted?.(undefined, step, options);
        step.onHighlighted?.(undefined, step, options);
        step.popover?.onPopoverRender?.({} as never, options);

        expect(raise).toHaveBeenCalledTimes(3);
        expect(ownHighlighted).toHaveBeenCalled();
        expect(ownPopoverRender).toHaveBeenCalled();
    });

    it('stays gone after dispose: a late raise() does not re-create the host', () => {
        const layer = createLayer();
        layer.raise();
        layer.dispose();

        layer.raise();

        expect(document.querySelector('.quickstart-tour-layer')).toBeNull();
    });

    // driver.js traps Tab with a keydown listener on window; `reachedDriver` stands in for it.
    describe('Tab in a CDK overlay that opened mid-step', () => {
        let layer: TourTopLayer;
        let reachedDriver: ReturnType<typeof vi.fn<(event: KeyboardEvent) => void>>;

        beforeEach(() => {
            reachedDriver = vi.fn<(event: KeyboardEvent) => void>();
            window.addEventListener('keydown', reachedDriver);
            layer = createLayer();
            layer.raise();
        });
        afterEach(() => {
            window.removeEventListener('keydown', reachedDriver);
            document.body.querySelectorAll('.cdk-overlay-pane, .page-button').forEach((element) => element.remove());
        });

        /** A button in a CDK overlay pane; inside the element driver.js highlights when `isHighlighted`. */
        function buttonInOverlay({ isHighlighted }: { isHighlighted: boolean }): HTMLButtonElement {
            const pane = appendToBody('cdk-overlay-pane');
            const container = isHighlighted ? document.createElement('div') : pane;
            if (isHighlighted) {
                container.className = 'driver-active-element';
                pane.appendChild(container);
            }
            const button = document.createElement('button');
            container.appendChild(button);
            return button;
        }

        function press(key: string, target: Element): void {
            target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
        }

        it('keeps Tab in the overlay away from driver.js, and only Tab', () => {
            const button = buttonInOverlay({ isHighlighted: false });

            press('Tab', button);
            expect(reachedDriver).not.toHaveBeenCalled();

            press('Escape', button);
            expect(reachedDriver).toHaveBeenCalledTimes(1);
        });

        it('leaves Tab to driver.js outside overlays and in the highlighted provider dropdown', () => {
            press('Tab', appendToBody('page-button'));
            press('Tab', buttonInOverlay({ isHighlighted: true }));

            expect(reachedDriver).toHaveBeenCalledTimes(2);
        });

        it('stops intercepting Tab once disposed', () => {
            const button = buttonInOverlay({ isHighlighted: false });

            layer.dispose();
            press('Tab', button);

            expect(reachedDriver).toHaveBeenCalledTimes(1);
        });
    });

    // jsdom has no Popover API; stub just enough of it to exercise the hide/show re-raise and the focus restore.
    describe('with the Popover API', () => {
        const openPopovers = new Set<Element>();
        const originalMatches = Element.prototype.matches;
        const popoverMethods = ['showPopover', 'hidePopover'] as const;
        const originalDescriptors = popoverMethods.map((name) =>
            Object.getOwnPropertyDescriptor(HTMLElement.prototype, name)
        );
        const showPopover = vi.fn(function (this: HTMLElement) {
            openPopovers.add(this);
        });
        const hidePopover = vi.fn(function (this: HTMLElement) {
            openPopovers.delete(this);
            // Browsers move focus out of a popover that is hidden.
            const focused = document.activeElement;
            if (focused instanceof HTMLElement && this.contains(focused)) {
                focused.blur();
            }
        });

        beforeEach(() => {
            showPopover.mockClear();
            hidePopover.mockClear();
            Object.defineProperty(HTMLElement.prototype, 'showPopover', { value: showPopover, configurable: true });
            Object.defineProperty(HTMLElement.prototype, 'hidePopover', { value: hidePopover, configurable: true });
            vi.spyOn(Element.prototype, 'matches').mockImplementation(function (this: Element, selector: string) {
                return selector === ':popover-open' ? openPopovers.has(this) : originalMatches.call(this, selector);
            });
        });

        afterEach(() => {
            popoverMethods.forEach((name, index) => {
                const original = originalDescriptors[index];
                if (original) {
                    Object.defineProperty(HTMLElement.prototype, name, original);
                } else {
                    delete (HTMLElement.prototype as Partial<HTMLElement>)[name];
                }
            });
            vi.restoreAllMocks();
            openPopovers.clear();
        });

        it('shows the host, then hides and re-shows it on each raise so it is the newest top-layer entry', () => {
            const layer = createLayer();

            layer.raise();
            layer.raise();

            expect(showPopover).toHaveBeenCalledTimes(2);
            expect(hidePopover).toHaveBeenCalledTimes(1);
            expect(hidePopover.mock.invocationCallOrder[0]).toBeLessThan(showPopover.mock.invocationCallOrder[1]);
        });

        it('keeps focus on the popover button across a re-raise', () => {
            const popover = appendToBody('driver-popover');
            const button = document.createElement('button');
            popover.appendChild(button);
            const layer = createLayer();
            layer.raise();
            button.focus();

            layer.raise();

            expect(document.activeElement).toBe(button);
        });

        it('hides the host before removing it on dispose', () => {
            const layer = createLayer();
            layer.raise();

            layer.dispose();

            expect(hidePopover).toHaveBeenCalledTimes(1);
            expect(openPopovers.size).toBe(0);
        });
    });
});
