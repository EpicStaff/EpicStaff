import { Component, inject } from '@angular/core';
import { RadioButtonComponent, ToggleSwitchComponent } from '@shared/components';
import { FlowEditorPreferences, FlowOnOpen } from '@shared/models';

import { UserPreferencesService } from '../../../../../../../services/auth/user-preferences.service';
import { LegacyFlowSettingsImportService } from '../../../../../../../visual-programming/services/legacy-flow-settings-import.service';
import { SettingsRowComponent } from '../../settings-section/settings-row.component';
import { SettingsSectionComponent } from '../../settings-section/settings-section.component';

/** One on/off row: what it shows as on, and the change switching it to `checked` saves. */
interface FlowEditorToggle {
    readonly label: string;
    readonly hint: string;
    readonly isOn: (preferences: FlowEditorPreferences) => boolean;
    readonly change: (checked: boolean) => Partial<FlowEditorPreferences>;
}

/** The same rows, in the same order, as the editor's flow settings panel, plus the minimap. */
const FLOW_EDITOR_TOGGLES: readonly FlowEditorToggle[] = [
    {
        label: 'Arrow colors',
        hint: 'Color each connection by the nodes it links',
        isOn: (preferences) => preferences.arrow_colors,
        change: (checked) => ({ arrow_colors: checked }),
    },
    {
        label: 'Show Inputs/Outputs',
        hint: "Show each node's input and output variables on the canvas",
        isOn: (preferences) => preferences.show_inputs_outputs,
        change: (checked) => ({ show_inputs_outputs: checked }),
    },
    {
        label: 'Curved connections',
        hint: 'Draw connections as curves instead of right angles',
        isOn: (preferences) => preferences.edge_style === 'adaptive-curve',
        change: (checked) => ({ edge_style: checked ? 'adaptive-curve' : 'orthogonal' }),
    },
    {
        label: 'Always show node numbers',
        hint: "Keep a node's number under its title, not only on hover",
        isOn: (preferences) => preferences.always_show_node_numbers,
        change: (checked) => ({ always_show_node_numbers: checked }),
    },
    {
        label: 'Highlight unused nodes',
        hint: 'Mark nodes that no run can reach from Start or a trigger',
        isOn: (preferences) => preferences.highlight_unused_nodes,
        change: (checked) => ({ highlight_unused_nodes: checked }),
    },
    {
        label: 'Show minimap',
        hint: 'Show the small overview map in the corner of the canvas',
        isOn: (preferences) => preferences.show_minimap,
        change: (checked) => ({ show_minimap: checked }),
    },
];

/** Settings → Flow editor: how every flow looks for the user, unless they change it for one flow in the editor. */
@Component({
    selector: 'app-flow-editor-section',
    templateUrl: './flow-editor-section.component.html',
    styleUrls: ['./flow-editor-section.component.scss'],
    imports: [ToggleSwitchComponent, RadioButtonComponent, SettingsSectionComponent, SettingsRowComponent],
})
export class FlowEditorSectionComponent {
    // Declared first: the field below reads it as it is created.
    private readonly preferencesService = inject(UserPreferencesService);

    protected readonly flowEditor = this.preferencesService.section('flow_editor');

    protected readonly toggles = FLOW_EDITOR_TOGGLES;
    protected readonly onOpenOptions: { value: FlowOnOpen; label: string }[] = [
        { value: 'fit', label: 'Fit the whole flow' },
        { value: 'restore', label: 'Restore where I left it' },
    ];
    protected readonly onOpenHint = 'Restore uses the last position and zoom on this device';

    constructor() {
        // Settings this browser kept before they moved to the account show here too.
        inject(LegacyFlowSettingsImportService).start();
    }

    protected setToggle(toggle: FlowEditorToggle, checked: boolean): void {
        this.preferencesService.patchSection('flow_editor', toggle.change(checked));
    }

    protected setOnOpen(value: unknown): void {
        if (value === 'fit' || value === 'restore') {
            this.preferencesService.patchSection('flow_editor', { on_open: value });
        }
    }
}
