import type { TourDefinitionFactory } from './core/guided-tour';
import { createCreateAgentTour } from './features/create-agent-tour/create-agent-tour.definition';
import { createQuickStartTour } from './features/quick-start-tour/quick-start-tour.definition';

/**
 * Every guided tour of the app, registered in app.config.ts. The order is the order auto-start considers them in and
 * the order the account menu lists them in. Add a tour here and nowhere else; app.tours.spec.ts checks every one.
 */
export const APP_TOURS: readonly TourDefinitionFactory[] = [createQuickStartTour, createCreateAgentTour];
