import { animate, style, transition, trigger } from '@angular/animations';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    effect,
    inject,
    input,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { Subject, timer } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import {
    GetScheduleTriggerNodeRequest,
    ScheduleEndType,
    ScheduleIntervalUnit,
    ScheduleRunMode,
    ScheduleTriggerNodeData,
    WeekdayCode,
} from '../../../../pages/flows-page/components/flow-visual-programming/models/schedule-trigger.model';
import { DatePickerComponent } from '../../../../shared/components/date-picker/date-picker.component';
import { ToggleSwitchComponent } from '../../../../shared/components/form-controls/toggle-switch/toggle-switch.component';
import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { HelpTooltipComponent } from '../../../../shared/components/help-tooltip/help-tooltip.component';
import { NumberStepperComponent } from '../../../../shared/components/number-stepper/number-stepper.component';
import { RadioButtonComponent } from '../../../../shared/components/radio-button/radio-button.component';
import { RoundButtonComponent } from '../../../../shared/components/round-button/round-button.component';
import { SelectComponent, SelectItem } from '../../../../shared/components/select/select.component';
import { TimePickerComponent } from '../../../../shared/components/time-picker/time-picker.component';
import { TimezoneSelectorComponent } from '../../../../shared/components/timezone-selector/timezone-selector.component';
import { ScheduleTriggerNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { FlowService } from '../../../services/flow.service';
import { SidePanelService } from '../../../services/side-panel.service';

const MIN_INTERVAL_SECONDS = 60;

const panelFadeSlide = trigger('panelFadeSlide', [
    transition(':enter', [
        style({ opacity: 0, transform: 'translateY(-4px)' }),
        animate('200ms ease-out', style({ opacity: 1, transform: 'translateY(0)' })),
    ]),
    transition(':leave', [animate('150ms ease-in', style({ opacity: 0, transform: 'translateY(-4px)' }))]),
]);

@Component({
    standalone: true,
    selector: 'app-schedule-trigger-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        DatePickerComponent,
        HelpTooltipComponent,
        NumberStepperComponent,
        RadioButtonComponent,
        RoundButtonComponent,
        SelectComponent,
        TimePickerComponent,
        TimezoneSelectorComponent,
        ToggleSwitchComponent,
    ],
    templateUrl: 'schedule-trigger-node-panel.component.html',
    styleUrls: ['schedule-trigger-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    animations: [panelFadeSlide],
})
export class ScheduleTriggerNodePanelComponent extends BaseSidePanel<ScheduleTriggerNodeModel> {
    public override readonly isExpanded = input<boolean>(false);
    public readonly graphId = input<number | null>(null);

    private initialNodeName = '';
    private readonly refreshedNextRun = signal<string | null | undefined>(undefined);
    private readonly refreshedIsActive = signal<boolean | undefined>(undefined);
    private readonly refreshedCurrentRuns = signal<number | undefined>(undefined);
    private readonly stopPolling$ = new Subject<void>();

    private readonly cdr = inject(ChangeDetectorRef);
    private readonly flowsApiService = inject(FlowsApiService);
    private readonly flowService = inject(FlowService);
    private readonly sidePanelService = inject(SidePanelService);

    constructor() {
        super();
        effect(() => {
            const nodeIsActive = this.node().data.isActive ?? false;
            const ctrl = this.form?.get('is_active');
            if (!ctrl) return;
            if (this.scheduleDirty()) return;
            if (ctrl.value !== nodeIsActive) {
                ctrl.patchValue(nodeIsActive, { emitEvent: false });
            }
        });
        this.sidePanelService.graphSaved$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            const backendId = this.node().backendId;
            if (backendId == null) return;
            this.stopPolling$.next();
            this.flowsApiService
                .getScheduleTriggerNode(backendId)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: (dto) => {
                        this.refreshedNextRun.set(dto.schedule?.next_run_date_time ?? null);
                        this.refreshedIsActive.set(dto.is_active);
                        this.refreshedCurrentRuns.set(dto.current_runs);
                        this.syncRefreshedDataToNode(dto);
                        this.schedulePoll(this.computeNextPollDelay(dto));
                    },
                    error: () => {},
                });
        });
        this.destroyRef.onDestroy(() => this.stopPolling$.next());
        this.schedulePoll(30_000);
    }

    protected submitted = signal(false);

    runMode = signal<string>('once');
    endMode = signal<string>('never');
    repeatUnit = signal<string>('hours');
    startRowError = signal<string>('');
    endRowError = signal<string>('');
    timezoneError = signal<string>('');
    intervalError = signal<string>('');

    minRepeatEvery = computed(() => (this.repeatUnit() === 'seconds' ? MIN_INTERVAL_SECONDS : 1));

    showRepeatFields = computed(() => this.runMode() === 'repeat');
    showWeekdays = computed(() => this.runMode() === 'repeat' && this.repeatUnit() === 'weeks');
    showEndDateTime = computed(() => this.endMode() === 'on_date');
    showMaxRuns = computed(() => this.endMode() === 'after_n_runs');

    readonly formattedNextRun = computed<string>(() => {
        const refreshed = this.refreshedNextRun();
        const iso = refreshed !== undefined ? refreshed : this.node().data.nextRunDateTime;
        if (!iso) return '—';
        const date = this.parseIsoToDate(iso);
        const time = this.parseIsoToTime(iso);
        return date && time ? `${date} at ${time}` : date || time || '—';
    });

    readonly runsLeft = computed<string>(() => {
        const refreshedCurrent = this.refreshedCurrentRuns();
        const currentRuns = refreshedCurrent !== undefined ? refreshedCurrent : (this.node().data.currentRuns ?? null);
        const maxRuns = this.node().data.maxRuns;
        if (currentRuns == null || maxRuns == null) return '—';
        return String(Math.max(0, maxRuns - currentRuns));
    });

    readonly runModeOptions = [
        { label: 'Once', value: 'once' },
        { label: 'Repeat', value: 'repeat' },
    ];

    readonly endModeOptions = [
        { label: 'Never', value: 'never' },
        { label: 'On date', value: 'on_date' },
        { label: 'After N runs', value: 'after_n_runs' },
    ];

    readonly repeatUnitItems: SelectItem[] = [
        { name: 'Seconds', value: 'seconds' },
        { name: 'Minutes', value: 'minutes' },
        { name: 'Hours', value: 'hours' },
        { name: 'Days', value: 'days' },
        { name: 'Weeks', value: 'weeks' },
        { name: 'Months', value: 'months' },
    ];

    readonly weekdays: Array<{ label: string; value: WeekdayCode; tooltip: string }> = [
        { label: 'S', value: 'sun', tooltip: 'Sunday' },
        { label: 'M', value: 'mon', tooltip: 'Monday' },
        { label: 'T', value: 'tue', tooltip: 'Tuesday' },
        { label: 'W', value: 'wed', tooltip: 'Wednesday' },
        { label: 'T', value: 'thu', tooltip: 'Thursday' },
        { label: 'F', value: 'fri', tooltip: 'Friday' },
        { label: 'S', value: 'sat', tooltip: 'Saturday' },
    ];

    repeatDays = signal<WeekdayCode[]>([]);
    hasStartDateTime = signal(false);
    startDateTimeDirty = signal(false);
    endDateTimeDirty = signal(false);
    scheduleDirty = signal(false);

    public override readonly isDirty = computed(() => {
        this.dirtyCheckTick();
        if (!this.form) return false;
        return this.scheduleDirty() || this.form.get('node_name')?.value !== this.initialNodeName;
    });

    toggleDay(value: WeekdayCode): void {
        const current = this.repeatDays();
        this.repeatDays.set(current.includes(value) ? current.filter((d) => d !== value) : [...current, value]);
        this.scheduleDirty.set(true);
    }

    public override onSave(): ScheduleTriggerNodeModel | null {
        if (this.scheduleDirty()) {
            this.submitted.set(true);

            const tz: string = this.form.getRawValue().timezone || 'UTC';
            const startErr = this.computeStartError(
                this.form.get('start_date')!.value,
                this.form.get('start_time')!.value
            );
            this.startRowError.set(startErr);

            const endErr = this.showEndDateTime()
                ? this.computeEndError(this.form.get('end_date')!.value, this.form.get('end_time')!.value, tz)
                : '';
            this.endRowError.set(endErr);

            if (startErr || endErr) {
                return null;
            }
        }

        const intervalErr = this.computeIntervalError();
        this.intervalError.set(intervalErr);
        if (intervalErr) return null;

        const hasConfiguredDateTime = !!(
            (this.form.get('start_date')!.value ?? '') &&
            (this.form.get('start_time')!.value ?? '')
        );
        const tzErr = hasConfiguredDateTime && !this.form.get('timezone')!.value ? 'Timezone is required' : '';
        this.timezoneError.set(tzErr);
        if (tzErr) return null;

        return super.onSave();
    }

    public override onSaveSilently(): ScheduleTriggerNodeModel | null {
        if (this.scheduleDirty()) {
            this.submitted.set(true);

            const tz: string = this.form.getRawValue().timezone || 'UTC';
            const startErr = this.computeStartError(
                this.form.get('start_date')!.value,
                this.form.get('start_time')!.value
            );
            this.startRowError.set(startErr);

            const endErr = this.showEndDateTime()
                ? this.computeEndError(this.form.get('end_date')!.value, this.form.get('end_time')!.value, tz)
                : '';
            this.endRowError.set(endErr);

            if (startErr || endErr) {
                return null;
            }
        }

        const intervalErr = this.computeIntervalError();
        this.intervalError.set(intervalErr);
        if (intervalErr) return null;

        const hasConfiguredDateTime = !!(
            (this.form.get('start_date')!.value ?? '') &&
            (this.form.get('start_time')!.value ?? '')
        );
        const tzErr = hasConfiguredDateTime && !this.form.get('timezone')!.value ? 'Timezone is required' : '';
        this.timezoneError.set(tzErr);
        if (tzErr) return null;

        return super.onSaveSilently();
    }

    /**
     * The global "Save Flow" action (`FlowGraphComponent.emitSave()`) captures the open panel
     * via `captureForValidation()`. The base implementation always returns a node (so panels
     * like the task node panel can report their own invalid state via a flow-wide toast
     * instead of a hard client-side abort) — but this panel's schedule/timezone checks aren't
     * reactive-form controls, so they need to run and surface their own inline errors, and a
     * save with bad schedule data must never reach the backend. Delegating to
     * `onSaveSilently()` (which does exactly that: sets `submitted`/`startRowError`/
     * `endRowError`/`timezoneError` and returns `null` on failure) restores the exact
     * pre-existing behavior for this panel.
     */
    public override captureForValidation(): ScheduleTriggerNodeModel | null {
        return this.onSaveSilently();
    }

    initializeForm(): FormGroup {
        this.refreshedNextRun.set(undefined);
        this.refreshedIsActive.set(undefined);
        this.refreshedCurrentRuns.set(undefined);
        this.initialNodeName = this.node().node_name;
        this.submitted.set(false);
        this.startRowError.set('');
        this.endRowError.set('');
        this.timezoneError.set('');
        this.intervalError.set('');
        this.startDateTimeDirty.set(false);
        this.endDateTimeDirty.set(false);
        this.scheduleDirty.set(false);

        const data = this.node().data;

        const isNewNode = !data.startDateTime;
        const future = isNewNode ? this.defaultFutureDateTime() : null;
        const defaultDate = isNewNode ? this.formatCurrentDate(future!) : this.parseIsoToDate(data.startDateTime);
        const defaultTime = isNewNode ? this.formatCurrentTime(future!) : this.parseIsoToTime(data.startDateTime);

        // Pre-sync signals so visibility computeds are correct before the template renders.
        // These subscriptions are attached after fb.group(), so we set them manually here.
        this.runMode.set(data.runMode ?? 'once');
        this.endMode.set(data.endType ?? 'never');
        this.repeatUnit.set(data.intervalUnit ?? 'hours');
        this.repeatDays.set([...(data.weekdays ?? [])]);
        this.hasStartDateTime.set(isNewNode || !!data.startDateTime);

        // Initial values are passed directly to fb.group() — Angular does NOT emit
        // valueChanges during construction, so live validators won't fire for loaded data.
        const fg = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            start_date: [defaultDate],
            start_time: [defaultTime],
            run_mode: [data.runMode ?? 'once'],
            repeat_every: [data.intervalEvery ?? 1],
            repeat_unit: [data.intervalUnit ?? 'hours'],
            end_mode: [data.endType ?? 'never'],
            end_date: [this.parseIsoToDate(data.endDateTime ?? '')],
            end_time: [this.parseIsoToTime(data.endDateTime ?? '')],
            max_runs: [data.maxRuns ?? 1],
            is_active: [isNewNode ? false : (data.isActive ?? true)],
            timezone: [this.resolveTimezone(data.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone)],
        });

        if (!this.hasStartDateTime()) {
            fg.get('is_active')!.disable({ emitEvent: false });
        }

        fg.get('run_mode')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((v) => this.runMode.set(v ?? 'once'));

        fg.get('end_mode')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((v) => this.endMode.set(v ?? 'never'));

        fg.get('repeat_unit')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((v) => {
                this.repeatUnit.set(v ?? 'hours');
                const everyCtrl = fg.get('repeat_every')!;
                const min = this.minRepeatEvery();
                if ((everyCtrl.value ?? 0) < min) {
                    everyCtrl.setValue(min);
                }
                this.intervalError.set('');
            });

        fg.get('repeat_every')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.intervalError.set(''));

        fg.get('start_date')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.startDateTimeDirty.set(true));
        fg.get('start_time')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.startDateTimeDirty.set(true));
        fg.get('end_date')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.endDateTimeDirty.set(true));
        fg.get('end_time')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.endDateTimeDirty.set(true));

        const scheduleFields = [
            'start_date',
            'start_time',
            'run_mode',
            'repeat_every',
            'repeat_unit',
            'end_mode',
            'end_date',
            'end_time',
            'max_runs',
            'is_active',
            'timezone',
        ] as const;
        scheduleFields.forEach((field) => {
            fg.get(field)!
                .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe(() => this.scheduleDirty.set(true));
        });

        const validateStart = () => {
            this.startRowError.set(this.computeStartError(fg.get('start_date')!.value, fg.get('start_time')!.value));
        };
        fg.get('start_date')!.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(validateStart);
        fg.get('start_time')!.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(validateStart);
        fg.get('timezone')!.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(validateStart);

        const validateEnd = () => {
            if (this.showEndDateTime()) {
                const tz: string = fg.get('timezone')!.value || 'UTC';
                this.endRowError.set(this.computeEndError(fg.get('end_date')!.value, fg.get('end_time')!.value, tz));
            }
        };
        fg.get('end_date')!.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(validateEnd);
        fg.get('end_time')!.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(validateEnd);
        fg.get('start_date')!.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(validateEnd);
        fg.get('start_time')!.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(validateEnd);
        fg.get('timezone')!.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(validateEnd);

        const updateActiveState = () => {
            const d = fg.get('start_date')!.value;
            const t = fg.get('start_time')!.value;
            const has = !!(d && t);
            this.hasStartDateTime.set(has);
            const ctrl = fg.get('is_active')!;
            if (!has) {
                ctrl.setValue(false, { emitEvent: false });
                ctrl.disable({ emitEvent: false });
            } else {
                ctrl.enable({ emitEvent: false });
            }
        };
        fg.get('start_date')!.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(updateActiveState);
        fg.get('start_time')!.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(updateActiveState);

        const backendId = this.node().backendId;
        if (backendId != null) {
            this.flowsApiService
                .getScheduleTriggerNode(backendId)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: (dto) => {
                        this.refreshedNextRun.set(dto.schedule?.next_run_date_time ?? null);
                        this.refreshedIsActive.set(dto.is_active);
                        this.refreshedCurrentRuns.set(dto.current_runs);
                        this.syncRefreshedDataToNode(dto, false);
                        this.stopPolling$.next();
                        this.schedulePoll(this.computeNextPollDelay(dto));
                    },
                    error: () => {},
                });
        }

        return fg;
    }

    /**
     * Extracts "dd.mm.yyyy" from a naive or offset-bearing ISO-8601 string.
     * Uses string splitting — no Date constructor — so the result is always
     * the wall-clock date written in the string, unaffected by browser timezone.
     * Handles both naive ("2026-05-01T09:00:00") and offset ("…+03:00") input.
     */
    private parseIsoToDate(iso: string): string {
        if (!iso) return '';
        const datePart = iso.split('T')[0]; // "2026-05-01"
        const segs = datePart.split('-');
        if (segs.length !== 3) return '';
        const [y, m, d] = segs;
        if (!y || !m || !d) return '';
        return `${d}.${m}.${y}`;
    }

    /**
     * Extracts "HH:MM" (24-hour) from a naive or offset-bearing ISO-8601 string.
     * Uses string splitting — no Date constructor — so the result is always
     * the wall-clock time written in the string, unaffected by browser timezone.
     * Handles both naive ("2026-05-01T09:00:00") and offset ("…+03:00") input.
     */
    private parseIsoToTime(iso: string): string {
        if (!iso) return '';
        const timePart = iso.split('T')[1];
        if (!timePart) return '';
        const [hStr, minStr] = timePart.slice(0, 5).split(':');
        if (!hStr || !minStr) return '';
        const h = parseInt(hStr, 10);
        const min = parseInt(minStr, 10);
        if (isNaN(h) || isNaN(min)) return '';
        return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
    }

    private computeIntervalError(): string {
        if (!this.showRepeatFields()) return '';

        const every = this.form.get('repeat_every')!.value;
        const min = this.minRepeatEvery();
        if (every != null && every >= min) return '';

        return this.repeatUnit() === 'seconds'
            ? `Interval must be at least ${MIN_INTERVAL_SECONDS} seconds.`
            : `Interval must be at least ${min}.`;
    }

    private computeStartError(dateVal: string | null, timeVal: string | null): string {
        const date = dateVal ?? '';
        const time = timeVal ?? '';

        if (this.submitted()) {
            if (!time && !date) return 'Start time and date are required';
            if (!time) return 'Start time is required';
            if (!date) return 'Start date is required';
        }

        if (!date || !/^\d{2}\.\d{2}\.\d{4}$/.test(date)) return '';

        const d = parseInt(date.slice(0, 2), 10);
        const m = parseInt(date.slice(3, 5), 10) - 1;
        const y = parseInt(date.slice(6), 10);
        const parsed = new Date(y, m, d);
        if (parsed.getFullYear() !== y || parsed.getMonth() !== m || parsed.getDate() !== d) {
            return 'Invalid start date';
        }

        return '';
    }

    private computeEndError(dateVal: string | null, timeVal: string | null, tz: string): string {
        const date = dateVal ?? '';
        const time = timeVal ?? '';

        if (this.submitted()) {
            if (!time && !date) return 'End time and date are required';
            if (!time) return 'End time is required';
            if (!date) return 'End date is required';
        }

        if (!date || !/^\d{2}\.\d{2}\.\d{4}$/.test(date)) return '';

        const d = parseInt(date.slice(0, 2), 10);
        const m = parseInt(date.slice(3, 5), 10) - 1;
        const y = parseInt(date.slice(6), 10);
        const parsed = new Date(y, m, d);
        if (parsed.getFullYear() !== y || parsed.getMonth() !== m || parsed.getDate() !== d) {
            return 'Invalid end date';
        }

        const startDateStr = this.form.get('start_date')?.value ?? '';
        const startTimeStr = this.form.get('start_time')?.value ?? '';
        if (startDateStr && /^\d{2}\.\d{2}\.\d{4}$/.test(startDateStr)) {
            const sy = parseInt(startDateStr.slice(6), 10);
            const sm = parseInt(startDateStr.slice(3, 5), 10) - 1;
            const sd = parseInt(startDateStr.slice(0, 2), 10);
            const parsedStart = new Date(sy, sm, sd);

            const timeToMinutes = (t: string): number => {
                const tm = t.match(/^(\d{1,2}):(\d{2})$/);
                if (!tm) return 0;
                return parseInt(tm[1], 10) * 60 + parseInt(tm[2], 10);
            };

            const endTs = parsed.getTime() + timeToMinutes(time) * 60_000;
            const startTs = parsedStart.getTime() + timeToMinutes(startTimeStr) * 60_000;

            if (endTs <= startTs) {
                return 'End date and time must be after start date and time';
            }
        }

        if (!this.endDateTimeDirty()) return '';
        if (!(this.form?.getRawValue().is_active ?? true) && this.node().backendId != null) return '';

        const {
            year: nowYear,
            month: nowMonth,
            day: nowDay,
            hour: nowHour,
            minute: nowMin,
        } = this.getNowInTimezone(tz);
        const today = new Date(nowYear, nowMonth - 1, nowDay);

        if (parsed.getTime() < today.getTime()) {
            return 'End date cannot be in the past';
        }

        if (parsed.getTime() === today.getTime() && time) {
            const match = time.match(/^(\d{1,2}):(\d{2})$/);
            if (match) {
                const h = parseInt(match[1], 10);
                const min = parseInt(match[2], 10);
                if (h < nowHour || (h === nowHour && min <= nowMin)) {
                    return 'End time cannot be in the past for today';
                }
            }
        }

        return '';
    }

    private isStrictAutoGeneratedName(name: string): boolean {
        if (/^Schedule Trigger #\d+$/.test(name)) return true;
        if (name === 'One-time schedule') return true;
        // Accept both legacy "at HH:MM" and new "at HH-MM" formats, with optional " #N" suffix.
        if (
            /^Once on \d{2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4} at \d{2}[:\-]\d{2}(?: #\d+)?$/.test(
                name
            )
        )
            return true;

        const MONTHS = 'Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec';
        const DAYS = 'Sun|Mon|Tue|Wed|Thu|Fri|Sat';
        const repeatPattern = new RegExp(
            '^Every (?:second|minute|hour|day|week|month|\\d+ (?:seconds|minutes|hours|days|weeks|months))' +
                '(?:' +
                ' on (?:' +
                `(?:(?:${DAYS})(?:, (?:${DAYS})){0,2})` +
                '|selected days' +
                ')' +
                ')?' +
                '(?:' +
                ` until \\d{2} (?:${MONTHS}) \\d{4}` +
                '| for \\d+ runs?' +
                ')?$'
        );
        return repeatPattern.test(name);
    }

    private formatDateForName(iso: string): string {
        const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        const [y, m, d] = iso.split('T')[0].split('-').map(Number);
        return `${String(d).padStart(2, '0')} ${MONTHS[m - 1]} ${y}`;
    }

    private generateScheduleName(data: ScheduleTriggerNodeData): string {
        if (data.runMode === 'once') {
            if (data.startDateTime) {
                // Use hyphen separator ("HH-MM") to avoid colon ambiguity in file-system
                // derived artifacts and visual display. Legacy names with "HH:MM" are still
                // recognised by isStrictAutoGeneratedName and rewritten on load.
                const rawTime = data.startDateTime.split('T')[1]?.slice(0, 5) ?? '';
                const timePart = rawTime.replace(':', '-');
                return `Once on ${this.formatDateForName(data.startDateTime)} at ${timePart}`;
            }
            return 'One-time schedule';
        }

        const n = data.intervalEvery ?? 1;
        const unit = data.intervalUnit ?? 'hours';
        const SINGULAR: Record<string, string> = {
            seconds: 'second',
            minutes: 'minute',
            hours: 'hour',
            days: 'day',
            weeks: 'week',
            months: 'month',
        };
        const PLURAL: Record<string, string> = {
            seconds: 'seconds',
            minutes: 'minutes',
            hours: 'hours',
            days: 'days',
            weeks: 'weeks',
            months: 'months',
        };
        let name = n === 1 ? `Every ${SINGULAR[unit] ?? unit}` : `Every ${n} ${PLURAL[unit] ?? unit}`;

        if (unit === 'weeks' && data.weekdays && data.weekdays.length > 0) {
            const ORDER = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
            const LABEL: Record<string, string> = {
                sun: 'Sun',
                mon: 'Mon',
                tue: 'Tue',
                wed: 'Wed',
                thu: 'Thu',
                fri: 'Fri',
                sat: 'Sat',
            };
            if (data.weekdays.length <= 3) {
                const sorted = [...data.weekdays].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b));
                name += ' on ' + sorted.map((d) => LABEL[d] ?? d).join(', ');
            } else {
                name += ' on selected days';
            }
        }

        if (data.endType === 'on_date' && data.endDateTime) {
            name += ` until ${this.formatDateForName(data.endDateTime)}`;
        } else if (data.endType === 'after_n_runs' && data.maxRuns != null) {
            name += ` for ${data.maxRuns} ${data.maxRuns === 1 ? 'run' : 'runs'}`;
        }

        return name;
    }

    createUpdatedNode(): ScheduleTriggerNodeModel {
        const f = this.form.value;
        const runMode: ScheduleRunMode = f.run_mode === 'repeat' ? 'repeat' : 'once';
        const endType: ScheduleEndType = runMode === 'once' ? 'never' : this.normalizeEndType(f.end_mode);

        let intervalEvery: number | null = null;
        let intervalUnit: ScheduleIntervalUnit | null = null;
        let weekdays: WeekdayCode[] = [];
        let endDateTime: string | null = null;
        let maxRuns: number | null = null;

        if (runMode === 'repeat') {
            intervalEvery = f.repeat_every ?? null;
            intervalUnit = (f.repeat_unit as ScheduleIntervalUnit) ?? null;
            const unitAllowsWeekdays = intervalUnit === 'weeks';
            weekdays = unitAllowsWeekdays ? [...this.repeatDays()] : [];

            if (endType === 'on_date') {
                endDateTime = this.buildDateTimeString(f.end_date ?? '', f.end_time ?? '');
            } else if (endType === 'after_n_runs') {
                maxRuns = f.max_runs ?? null;
            }
        }

        const refreshedNext = this.refreshedNextRun();
        const refreshedCurrent = this.refreshedCurrentRuns();

        const data: ScheduleTriggerNodeData = {
            isActive: f.is_active ?? false,
            runMode,
            startDateTime: this.buildDateTimeString(f.start_date ?? '', f.start_time ?? ''),
            intervalEvery,
            intervalUnit,
            weekdays,
            endType,
            endDateTime,
            maxRuns,
            currentRuns: refreshedCurrent !== undefined ? refreshedCurrent : (this.node().data.currentRuns ?? 0),
            timezone: (f.timezone as string | null) ?? '',
            nextRunDateTime: refreshedNext !== undefined ? refreshedNext : (this.node().data.nextRunDateTime ?? null),
        };

        const formName = f.node_name ?? this.node().node_name;
        const userChangedName = formName !== this.initialNodeName;
        let resolvedName: string;
        if (!userChangedName && this.isStrictAutoGeneratedName(this.initialNodeName)) {
            const baseName = this.generateScheduleName(data);
            const currentNodeId = this.node().id;
            if (this.uniqueNameValidator.isNameUnique(baseName, currentNodeId)) {
                resolvedName = baseName;
            } else {
                // Find the first unique suffix " #N" starting at 2.
                const MAX_SUFFIX = 1000;
                let suffix = 2;
                let candidate = `${baseName} #${suffix}`;
                while (suffix <= MAX_SUFFIX && !this.uniqueNameValidator.isNameUnique(candidate, currentNodeId)) {
                    suffix++;
                    candidate = `${baseName} #${suffix}`;
                }
                if (suffix > MAX_SUFFIX) {
                    console.error(
                        `[schedule-trigger] Could not find a unique name for "${baseName}" after ${MAX_SUFFIX} attempts`
                    );
                }
                resolvedName = candidate;
            }
        } else {
            resolvedName = formName;
        }

        if (resolvedName !== formName) {
            this.form.get('node_name')!.setValue(resolvedName, { emitEvent: false });
            this.initialNodeName = resolvedName;
            this.cdr.markForCheck();
        }

        return {
            ...this.node(),
            node_name: resolvedName,
            data,
        };
    }

    private normalizeTimezone(iana: string): string {
        // Europe/Kiev is the pre-2022 IANA alias — normalize to the canonical name.
        return iana === 'Europe/Kiev' ? 'Europe/Kyiv' : iana;
    }

    private resolveTimezone(raw: string | null | undefined): string | null {
        if (!raw) return null;
        const normalized = this.normalizeTimezone(raw);
        if (normalized === 'UTC' || normalized === 'Etc/UTC') return null;
        try {
            new Intl.DateTimeFormat('en', { timeZone: normalized });
            return normalized;
        } catch {
            return null;
        }
    }

    private getNowInTimezone(tz: string): { year: number; month: number; day: number; hour: number; minute: number } {
        const parts = new Intl.DateTimeFormat('en-US', {
            timeZone: tz,
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
        }).formatToParts(new Date());
        const get = (type: string) => parseInt(parts.find((p) => p.type === type)!.value, 10);
        return { year: get('year'), month: get('month'), day: get('day'), hour: get('hour'), minute: get('minute') };
    }

    private normalizeEndType(raw: string | null | undefined): ScheduleEndType {
        if (raw === 'on_date') return 'on_date';
        if (raw === 'after_n_runs' || raw === 'after_runs') return 'after_n_runs';
        return 'never';
    }

    /**
     * Combines "dd.mm.yyyy" date and "HH:MM" (24-hour) time into a naive ISO-8601
     * datetime string: "YYYY-MM-DDTHH:MM:00" — no UTC offset, no Z suffix.
     * Timezone is sent separately as the IANA string in schedule.timezone.
     * No Date constructor is used, so the result is always the exact wall-clock
     * time the user entered, unaffected by browser timezone.
     */
    private buildDateTimeString(date: string, time: string): string {
        if (!date || !time) return '';

        const dateMatch = date.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
        const timeMatch = time.match(/^(\d{1,2}):(\d{2})$/);
        if (!dateMatch || !timeMatch) return '';

        const d = parseInt(dateMatch[1], 10);
        const m = parseInt(dateMatch[2], 10);
        const y = parseInt(dateMatch[3], 10);
        const h = parseInt(timeMatch[1], 10);
        const min = parseInt(timeMatch[2], 10);

        if (d < 1 || d > 31 || m < 1 || m > 12 || h > 23 || min > 59) return '';

        const pad = (n: number) => String(n).padStart(2, '0');
        return `${y}-${pad(m)}-${pad(d)}T${pad(h)}:${pad(min)}:00`;
    }

    private defaultFutureDateTime(): Date {
        const d = new Date();
        d.setSeconds(0, 0);
        const rem = d.getMinutes() % 30;
        d.setMinutes(d.getMinutes() + (rem === 0 ? 30 : 30 - rem));
        return d;
    }

    private formatCurrentDate(d: Date): string {
        const dd = String(d.getDate()).padStart(2, '0');
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const yyyy = String(d.getFullYear());
        return `${dd}.${mm}.${yyyy}`;
    }

    private formatCurrentTime(d: Date): string {
        const h = d.getHours();
        const min = d.getMinutes();
        return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
    }

    private schedulePoll(delayMs: number): void {
        timer(delayMs)
            .pipe(takeUntil(this.stopPolling$))
            .subscribe(() => {
                const backendId = this.node().backendId;
                if (backendId == null) {
                    this.schedulePoll(60_000);
                    return;
                }
                this.flowsApiService
                    .getScheduleTriggerNode(backendId)
                    .pipe(takeUntil(this.stopPolling$))
                    .subscribe({
                        next: (dto) => {
                            this.refreshedNextRun.set(dto.schedule?.next_run_date_time ?? null);
                            this.refreshedIsActive.set(dto.is_active);
                            this.refreshedCurrentRuns.set(dto.current_runs);
                            this.syncRefreshedDataToNode(dto);
                            this.schedulePoll(this.computeNextPollDelay(dto));
                        },
                        error: () => {
                            this.schedulePoll(30_000);
                        },
                    });
            });
    }

    private syncRefreshedDataToNode(dto: GetScheduleTriggerNodeRequest, includeIsActive = true): void {
        if (this.scheduleDirty()) return;
        const current = this.node();
        const newIsActive = includeIsActive ? dto.is_active : current.data.isActive;
        const newNextRun = dto.schedule?.next_run_date_time ?? null;
        const newCurrentRuns = dto.current_runs;
        if (
            current.data.isActive === newIsActive &&
            current.data.nextRunDateTime === newNextRun &&
            current.data.currentRuns === newCurrentRuns
        ) {
            return;
        }
        const updatedNode: ScheduleTriggerNodeModel = {
            ...current,
            data: {
                ...current.data,
                isActive: newIsActive,
                nextRunDateTime: newNextRun,
                currentRuns: newCurrentRuns,
            },
        };
        this.flowService.updateNode(updatedNode);
    }

    private computeNextPollDelay(dto: GetScheduleTriggerNodeRequest): number {
        if (!dto.is_active) return 60_000;
        const next = dto.schedule?.next_run_date_time;
        if (!next) return 1_000;
        const msUntilRun = new Date(next).getTime() - Date.now();
        if (msUntilRun <= 2 * 60_000) return 5_000;
        if (msUntilRun <= 10 * 60_000) return 15_000;
        return 30_000;
    }
}
