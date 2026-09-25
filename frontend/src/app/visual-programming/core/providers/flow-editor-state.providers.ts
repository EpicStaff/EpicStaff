import { InjectionToken, Provider } from '@angular/core';

import { ClipboardService } from '../../services/clipboard.service';
import { FlowService } from '../../services/flow.service';
import { NodeFactoryService } from '../../services/node-factory.service';
import { NodeNameValidatorService } from '../../services/node-name-validator.service';
import { SidePanelService } from '../../services/side-panel.service';
import { UndoRedoService } from '../../services/undo-redo.service';
import { UniqueNodeNameValidatorService } from '../../services/unique-node-name.validator';

/**
 * Every service that holds flow-editor state or reads it through FlowService. They are
 * `providedIn: 'root'` for the live editor; a component that lists this array in its
 * `providers` gets an isolated editor (e.g. the version preview) whose canvas, panels,
 * undo stack and clipboard never touch the live ones.
 *
 * Keep the list complete: a state-holding service left out would resolve to the root
 * instance and leak between the two editors. Stateless HTTP services and user preferences
 * (FlowSettingsService) are deliberately shared.
 */
export const FLOW_EDITOR_STATE_PROVIDERS: Provider[] = [
    FlowService,
    UndoRedoService,
    SidePanelService,
    ClipboardService,
    NodeFactoryService,
    NodeNameValidatorService,
    UniqueNodeNameValidatorService,
];

/** True when the flow editor must not change the flow (canvas and node panels). */
export const FLOW_EDITOR_READ_ONLY = new InjectionToken<boolean>('FLOW_EDITOR_READ_ONLY', {
    providedIn: 'root',
    factory: () => false,
});
