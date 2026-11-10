import { AfterViewInit, Directive, ElementRef, EventEmitter, Input, NgZone, OnDestroy, Output } from '@angular/core';

/**
 * Hosts with one parent share its width: a label collapsing frees room for the others, one expanding takes it away.
 * Each deciding alone, a frame after the others moved, they kept flipping one another; so direct siblings decide
 * together. Hosts under different parents (wrapped in a span of their own, say) stay independent.
 *
 * One resize observer serves every host and settles each affected group once per resize, however many of its hosts
 * and their ancestors changed size.
 */
class CollapseGroups {
    private readonly groups = new Map<Element, Set<CollapseOnOverflowDirective>>();
    private readonly observedCounts = new Map<Element, number>();
    private resizeObserver: ResizeObserver | null = null;

    public join(member: CollapseOnOverflowDirective, parent: Element, observed: Element[]): void {
        const group = this.groups.get(parent) ?? new Set<CollapseOnOverflowDirective>();
        group.add(member);
        this.groups.set(parent, group);

        // Settled right away: resize callbacks run after layout and before paint, so the first frame at a new
        // width (a sidebar closing in one step) already shows the labels that fit.
        this.resizeObserver ??= new ResizeObserver((entries) => this.settleGroupsAffectedBy(entries));
        for (const element of observed) {
            const count = this.observedCounts.get(element) ?? 0;
            if (count === 0) {
                this.resizeObserver.observe(element);
            }
            this.observedCounts.set(element, count + 1);
        }
    }

    public leave(member: CollapseOnOverflowDirective, parent: Element, observed: Element[]): void {
        const group = this.groups.get(parent);
        group?.delete(member);
        if (group?.size === 0) {
            this.groups.delete(parent);
        }

        for (const element of observed) {
            const count = (this.observedCounts.get(element) ?? 1) - 1;
            if (count === 0) {
                this.observedCounts.delete(element);
                this.resizeObserver?.unobserve(element);
            } else {
                this.observedCounts.set(element, count);
            }
        }

        if (this.groups.size === 0) {
            this.resizeObserver?.disconnect();
            this.resizeObserver = null;
        }
    }

    /** The group's hosts in DOM order: the first ones collapse first. */
    public membersOf(parent: Element): CollapseOnOverflowDirective[] {
        return [...(this.groups.get(parent) ?? [])].sort((first, second) =>
            first.host.compareDocumentPosition(second.host) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1
        );
    }

    private settleGroupsAffectedBy(entries: ResizeObserverEntry[]): void {
        const resized = entries.map((entry) => entry.target);
        for (const [parent, group] of this.groups) {
            const affected = [...group].some((member) => resized.some((target) => target.contains(member.host)));
            if (affected) {
                CollapseOnOverflowDirective.settle(this.membersOf(parent));
            }
        }
    }
}

const collapseGroups = new CollapseGroups();

@Directive({
    selector: '[appCollapseOnOverflow]',
})
export class CollapseOnOverflowDirective implements AfterViewInit, OnDestroy {
    @Input('appCollapseOnOverflow') public collapseOnOverflowEnabled = true;
    @Input() public collapseOnOverflowTarget = '.btn-content';
    @Input() public collapseOnOverflowClass = 'is-collapsed';
    @Input() public collapseOnOverflowRequireSelector = '';
    @Input() public collapseOnOverflowCheckExternalClip = true;
    @Output() public collapseOnOverflowChange = new EventEmitter<boolean>();

    private mutationObserver: MutationObserver | null = null;
    private frameId: number | null = null;
    private collapsed = false;
    private naturalWidth = 0;
    private groupParent: Element | null = null;
    private observedElements: Element[] = [];

    constructor(
        private readonly hostRef: ElementRef<HTMLElement>,
        private readonly ngZone: NgZone
    ) {}

    public get host(): HTMLElement {
        return this.hostRef.nativeElement;
    }

    /**
     * Settles a group in one pass, before the frame paints: all collapse, then they get their labels back from the
     * last (a header's main action) towards the first, up to the first that leaves an expanded label without room;
     * it and the ones before it stay icons. So buttons collapse left to right and no label shows before an icon.
     * The outcome depends on the width alone, not on what the previous frame showed, so labels never flip back and
     * forth while the width changes.
     */
    public static settle(members: CollapseOnOverflowDirective[]): void {
        // Our own class writes must not re-trigger the observers: that was a ~60fps feedback loop.
        for (const member of members) {
            member.cancelScheduledEvaluate();
            member.mutationObserver?.disconnect();
        }

        let changed: CollapseOnOverflowDirective[] = [];
        try {
            const collapsible = members.filter((member) => member.canCollapse());

            // Every label at its full width, in one layout: what each needs to show without an ellipsis.
            collapsible.forEach((member) => member.applyCollapsedClass(false));
            const restoreTargets = collapsible.map((member) => member.unconstrainTarget());
            collapsible.forEach((member) => (member.naturalWidth = member.targetWidth()));
            restoreTargets.forEach((restore) => restore());

            collapsible.forEach((member) => member.applyCollapsedClass(true));

            const expanded = new Set<CollapseOnOverflowDirective>();
            for (const member of [...collapsible].reverse()) {
                member.applyCollapsedClass(false);
                expanded.add(member);
                if ([...expanded].some((expandedMember) => expandedMember.isOverflowing())) {
                    member.applyCollapsedClass(true);
                    expanded.delete(member);
                    break;
                }
            }

            changed = members.filter((member) =>
                member.commitCollapsed(collapsible.includes(member) && !expanded.has(member))
            );
        } finally {
            members.forEach((member) => member.observeMutations());
        }

        // Once, after the pass: each emit inside it would run change detection with the observers disconnected.
        const listened = changed.filter((member) => member.collapseOnOverflowChange.observed);
        if (listened.length) {
            members[0].ngZone.run(() => {
                listened.forEach((member) => member.collapseOnOverflowChange.emit(member.collapsed));
            });
        }
    }

    public ngAfterViewInit(): void {
        this.ngZone.runOutsideAngular(() => {
            this.groupParent = this.host.parentElement;
            if (this.groupParent) {
                this.observedElements = this.hostAndAncestors();
                collapseGroups.join(this, this.groupParent, this.observedElements);
            }

            this.mutationObserver = new MutationObserver(() => this.scheduleEvaluate());
            this.observeMutations();

            this.scheduleEvaluate();
            setTimeout(() => this.scheduleEvaluate(), 0);
        });
    }

    public ngOnDestroy(): void {
        if (this.groupParent) {
            collapseGroups.leave(this, this.groupParent, this.observedElements);
            this.groupParent = null;
            this.observedElements = [];
        }

        this.mutationObserver?.disconnect();
        this.mutationObserver = null;

        this.cancelScheduledEvaluate();
    }

    private scheduleEvaluate(): void {
        if (this.frameId !== null) {
            return;
        }

        this.frameId = requestAnimationFrame(() => {
            this.frameId = null;
            CollapseOnOverflowDirective.settle(this.groupParent ? collapseGroups.membersOf(this.groupParent) : [this]);
        });
    }

    private canCollapse(): boolean {
        if (!this.collapseOnOverflowEnabled) {
            return false;
        }
        if (
            this.collapseOnOverflowRequireSelector &&
            !this.host.querySelector(this.collapseOnOverflowRequireSelector)
        ) {
            return false;
        }
        return this.host.querySelector(this.collapseOnOverflowTarget) !== null;
    }

    private isOverflowing(): boolean {
        const target = this.host.querySelector<HTMLElement>(this.collapseOnOverflowTarget);
        if (!target) {
            return false;
        }

        // In fractional pixels: a row a pixel short squeezes each label by a fraction of one, already an ellipsis,
        // which the whole-pixel scrollWidth and clientWidth round away.
        const horizontalOverflow = this.naturalWidth - target.getBoundingClientRect().width > 0.01;
        const verticalOverflow = target.scrollHeight - target.clientHeight > 2;
        const externallyClipped = this.collapseOnOverflowCheckExternalClip ? this.isExternallyClipped() : false;

        return horizontalOverflow || verticalOverflow || externallyClipped;
    }

    /** Lets the label take its full width, whatever squeezes or caps it; returns what puts it back. */
    private unconstrainTarget(): () => void {
        const target = this.host.querySelector<HTMLElement>(this.collapseOnOverflowTarget);
        if (!target) {
            return () => undefined;
        }

        const previousStyle = target.style.cssText;
        target.style.flex = 'none';
        target.style.width = 'max-content';
        target.style.maxWidth = 'none';
        return () => (target.style.cssText = previousStyle);
    }

    private targetWidth(): number {
        return this.host.querySelector<HTMLElement>(this.collapseOnOverflowTarget)?.getBoundingClientRect().width ?? 0;
    }

    // The class alone, to measure a layout; commitCollapsed records the outcome.
    private applyCollapsedClass(collapsed: boolean): void {
        this.host.classList.toggle(this.collapseOnOverflowClass, collapsed);
    }

    /** Applies the outcome; true when it differs from the last one. */
    private commitCollapsed(next: boolean): boolean {
        this.applyCollapsedClass(next);

        const changed = this.collapsed !== next;
        this.collapsed = next;
        return changed;
    }

    private cancelScheduledEvaluate(): void {
        if (this.frameId !== null) {
            cancelAnimationFrame(this.frameId);
            this.frameId = null;
        }
    }

    private observeMutations(): void {
        this.mutationObserver?.observe(this.host, {
            childList: true,
            subtree: true,
            characterData: true,
            attributes: true,
        });
    }

    private isExternallyClipped(): boolean {
        const rect = this.host.getBoundingClientRect();
        const visibleWidth = this.getVisibleWidth(rect);
        return visibleWidth + 1 < rect.width;
    }

    private getVisibleWidth(targetRect: DOMRect): number {
        let left = Math.max(0, targetRect.left);
        let right = Math.min(window.innerWidth, targetRect.right);

        let ancestor: HTMLElement | null = this.host.parentElement;
        while (ancestor) {
            const overflowX = window.getComputedStyle(ancestor).overflowX;
            if (overflowX !== 'visible') {
                const rect = ancestor.getBoundingClientRect();
                left = Math.max(left, rect.left);
                right = Math.min(right, rect.right);
            }
            ancestor = ancestor.parentElement;
        }

        return Math.max(0, right - left);
    }

    private hostAndAncestors(): Element[] {
        const elements: Element[] = [];
        let element: Element | null = this.host;
        while (element) {
            elements.push(element);
            element = element.parentElement;
        }
        return elements;
    }
}
