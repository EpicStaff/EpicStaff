import { DefaultUrlSerializer, UrlTree } from '@angular/router';

import { isAtOrUnderPath } from '../engine/tour-url-match';
import { TourDefinition, TourStep } from '../model/tour-definition';

/**
 * The rule for tour keys, and the rule the future generic progress storage must accept. Anchors follow it too, so an
 * anchor needs no escaping in a selector.
 */
const TOUR_KEY_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const TOUR_KEY_MAX_LENGTH = 64;
const TOUR_KEY_RULE = `lowercase letters and digits in words joined by single hyphens, at most ${TOUR_KEY_MAX_LENGTH} characters`;

const urlSerializer = new DefaultUrlSerializer();

export interface TourDefinitionsCheck {
    /** The tours without problems, in the order given; of tours given under one key, only the first. */
    readonly validTours: readonly TourDefinition[];
    /** Every problem found, one sentence each; empty when every tour is valid. */
    readonly problems: readonly string[];
}

/**
 * Checks tour definitions for the mistakes that can be found without running them: keys, step ids, Back targets,
 * anchors, and steps that could never move on. Pure, so a feature's spec can check its own definition with it.
 */
export function validateTourDefinitions(tours: readonly TourDefinition[]): TourDefinitionsCheck {
    const keys = tours.map((tour) => tour.key);
    const problems = duplicates(keys).map((key) => `Tour key "${key}" is registered more than once.`);
    const validTours: TourDefinition[] = [];
    tours.forEach((tour, index) => {
        const ownProblems = tourProblems(tour);
        problems.push(...ownProblems);
        const isLaterDuplicate = keys.indexOf(tour.key) !== index;
        if (ownProblems.length === 0 && !isLaterDuplicate) {
            validTours.push(tour);
        }
    });
    return { validTours, problems };
}

function tourProblems(tour: TourDefinition): string[] {
    const problems: string[] = [];
    if (!isTourName(tour.key)) {
        problems.push(`Tour key "${tour.key}" must be ${TOUR_KEY_RULE}.`);
    }
    if (tour.steps.length === 0) {
        problems.push(`Tour "${tour.key}" has no steps.`);
    }
    const stepIds = tour.steps.map((step) => step.id);
    for (const stepId of duplicates(stepIds)) {
        problems.push(`Tour "${tour.key}" has more than one step "${stepId}".`);
    }
    for (const step of tour.steps) {
        problems.push(
            ...stepProblems(step, stepIds).map((problem) => `Step "${step.id}" of tour "${tour.key}" ${problem}`)
        );
    }
    return problems;
}

/** Each problem completes the sentence `Step "<id>" of tour "<key>" …`. */
function stepProblems(step: TourStep, stepIds: readonly string[]): string[] {
    const problems: string[] = [];
    if (step.back && !stepIds.includes(step.back.toStep)) {
        problems.push(`goes back to an unknown step "${step.back.toStep}".`);
    }
    const anchors = [step.target?.anchor, step.advance?.kind === 'anchor-appears' ? step.advance.anchor : undefined];
    for (const anchor of anchors) {
        if (anchor !== undefined && !isTourName(anchor)) {
            problems.push(`has the anchor "${anchor}", which must be ${TOUR_KEY_RULE}.`);
        }
    }
    const advance = step.advance;
    const isMovedOnByTargetClick =
        advance?.kind === 'target-click' || (advance?.kind === 'navigation' && advance.onTargetClick === true);
    if (isMovedOnByTargetClick && !step.target) {
        problems.push('moves on by a click on its target, but has no target.');
    }
    if (!canMoveOn(step)) {
        problems.push('hides Next, and nothing else moves it on.');
    }
    if (advance?.kind === 'navigation' && advance.followNavigationsInto !== undefined) {
        const url = parsedUrl(advance.url);
        const section = parsedUrl(advance.followNavigationsInto);
        if (!url || !section) {
            problems.push(
                `navigates to "${advance.url}" following "${advance.followNavigationsInto}", which do not both parse as URLs.`
            );
        } else if (!isAtOrUnderPath(url, section)) {
            problems.push(
                `follows navigations into "${advance.followNavigationsInto}", which does not contain its URL "${advance.url}".`
            );
        }
    }
    return problems;
}

/** Whether the user has a way on besides Skip and close: the Next button, or an advance of its own. */
function canMoveOn(step: TourStep): boolean {
    if (step.buttons?.next !== false) {
        return true;
    }
    const advance = step.advance;
    if (!advance || advance.kind === 'next') {
        return false;
    }
    // A navigation step's own way on is Next; without it, only a click on the target starts the navigation.
    return advance.kind !== 'navigation' || advance.onTargetClick === true;
}

function isTourName(name: string): boolean {
    return name.length <= TOUR_KEY_MAX_LENGTH && TOUR_KEY_PATTERN.test(name);
}

function parsedUrl(url: string): UrlTree | null {
    try {
        return urlSerializer.parse(url);
    } catch {
        return null;
    }
}

function duplicates(values: readonly string[]): string[] {
    return [...new Set(values.filter((value, index) => values.indexOf(value) !== index))];
}
