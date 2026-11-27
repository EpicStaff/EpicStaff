import { computed, inject, Injectable } from '@angular/core';
import { FlowEdgeStyle, FlowEditorPreferences, FlowOnOpen } from '@shared/models';
import { effectiveZone, normalizeIana } from '@shared/utils';

import { UserPreferencesService } from '../../services/auth/user-preferences.service';
import { FlowViewOverrideService } from './flow-view-override.service';
import { FlowViewOverride } from './flow-view-settings-api.service';

/** A change to the open flow's settings. A `null` timezone makes the flow follow the account's default again. */
export type FlowViewChange = Partial<FlowEditorPreferences> & { readonly default_timezone?: string | null };

/**
 * How the flow editor looks for the signed-in user: their account's flow editor preferences, with their own
 * override for the open flow on top. A change made in the editor goes to that override only, so it changes neither
 * the account nor what anybody else sees. The same goes for the timezone new schedule triggers open with: the
 * account's default timezone, unless the user set one for the open flow.
 */
@Injectable({ providedIn: 'root' })
export class FlowSettingsService {
    private readonly preferences = inject(UserPreferencesService);
    private readonly account = this.preferences.section('flow_editor');
    private readonly accountGeneral = this.preferences.section('general');
    private readonly overrides = inject(FlowViewOverrideService);

    private readonly effective = computed<FlowEditorPreferences>(() => ({
        ...this.account(),
        ...this.overrides.override(),
    }));

    readonly arrowColorsEnabled = computed<boolean>(() => this.effective().arrow_colors);
    readonly showInputsOutputs = computed<boolean>(() => this.effective().show_inputs_outputs);
    readonly edgeStyle = computed<FlowEdgeStyle>(() => this.effective().edge_style);
    readonly alwaysShowNodeNumbers = computed<boolean>(() => this.effective().always_show_node_numbers);
    readonly highlightUnusedNodes = computed<boolean>(() => this.effective().highlight_unused_nodes);
    readonly showMinimap = computed<boolean>(() => this.effective().show_minimap);
    readonly onOpen = computed<FlowOnOpen>(() => this.effective().on_open);
    /** The zone the account gives new schedule triggers: its default timezone, or the browser's while none is set. */
    readonly accountScheduleZone = computed<string>(() => effectiveZone(this.accountGeneral().default_timezone));
    /** The open flow's own zone for new schedule triggers, or `null` while the flow follows the account's. */
    readonly flowScheduleZone = computed<string | null>(() => this.overrides.override().default_timezone ?? null);
    /** The zone a schedule trigger created in the open flow starts with. */
    readonly newScheduleZone = computed<string>(() => {
        const flowZone = this.flowScheduleZone();
        return flowZone ? normalizeIana(flowZone) : this.accountScheduleZone();
    });
    /** The open flow has settings of its own, so "Reset to my defaults" has something to drop. */
    readonly hasFlowOverride = computed(() => Object.keys(this.overrides.override()).length > 0);

    /**
     * Applies `change` to the open flow, for the signed-in user only. A value equal to the account's, or a `null`,
     * leaves the override, so the flow keeps following the account for it. The timezone is compared with the zone
     * the account stores, not the browser's: a zone picked for a flow whose account follows the browser stays put,
     * so the flow keeps it in any browser.
     */
    setForCurrentFlow(change: FlowViewChange): void {
        const accountZone = this.accountGeneral().default_timezone;
        const account: Readonly<Record<string, unknown>> = {
            ...this.account(),
            default_timezone: accountZone ? normalizeIana(accountZone) : null,
        };
        const merged: Record<string, unknown> = { ...this.overrides.override(), ...change };
        const override = Object.fromEntries(
            Object.entries(merged).filter(
                ([key, value]) => value !== undefined && value !== null && value !== account[key]
            )
        ) as FlowViewOverride;
        this.overrides.save(override);
    }

    /** Drops the open flow's own settings, the timezone included: it follows the account's settings again. */
    resetCurrentFlow(): void {
        this.overrides.reset();
    }
}
