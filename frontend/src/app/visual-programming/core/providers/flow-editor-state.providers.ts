import { Provider } from '@angular/core';

import { ClipboardService } from '../../services/clipboard.service';
import { FlowService } from '../../services/flow.service';
import { FlowReadOnlyService } from '../../services/flow-readonly.service';
import { FlowTestRunService } from '../../services/flow-test-run.service';
import { NodeAuthorshipStore } from '../../services/node-authorship.store';
import { NodeFactoryService } from '../../services/node-factory.service';
import { NodeNameValidatorService } from '../../services/node-name-validator.service';
import { SavedFlowStateService } from '../../services/saved-flow-state.service';
import { SidePanelService } from '../../services/side-panel.service';
import { UndoRedoService } from '../../services/undo-redo.service';
import { UniqueNodeNameValidatorService } from '../../services/unique-node-name.validator';
import { VersionPreviewNodeAuthorshipStore } from '../../services/version-preview-node-authorship.store';

/**
 * Every service that holds flow-editor state or reads it through FlowService. They are
 * `providedIn: 'root'` for the live editor; a component that lists this array in its
 * `providers` gets an isolated editor (e.g. the version preview) whose canvas, panels,
 * undo stack and clipboard never touch the live ones.
 *
 * Keep the list complete: a state-holding service left out would resolve to the root
 * instance and leak between the two editors. Stateless HTTP services and user preferences
 * (FlowSettingsService) are deliberately shared.
 *
 * FlowReadOnlyService is listed because it reads FLOW_EDITOR_PREVIEW: the root instance would
 * only ever see the root value (false), and the preview would be editable.
 *
 * NodeAuthorshipStore is the exception to `providedIn: 'root'`: the flow page provides the live
 * instance and replaces its contents on every graph load. This list gives the preview a
 * VersionPreviewNodeAuthorshipStore instead, under both tokens (one instance): the node details
 * read it as a NodeAuthorshipStore, the preview fills it with the version's recorded authorship.
 */
export const FLOW_EDITOR_STATE_PROVIDERS: Provider[] = [
    FlowService,
    UndoRedoService,
    FlowReadOnlyService,
    SidePanelService,
    SavedFlowStateService,
    ClipboardService,
    NodeFactoryService,
    NodeNameValidatorService,
    UniqueNodeNameValidatorService,
    VersionPreviewNodeAuthorshipStore,
    { provide: NodeAuthorshipStore, useExisting: VersionPreviewNodeAuthorshipStore },
    FlowTestRunService,
];
