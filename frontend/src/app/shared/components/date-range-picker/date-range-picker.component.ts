import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    EventEmitter,
    Input,
    OnChanges,
    Output,
    QueryList,
    signal,
    SimpleChanges,
    ViewChildren,
} from '@angular/core';
import { DateRangeFilter } from '@shared/models';

const MONTH_NAMES = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
];

type FieldGroup = 'start' | 'end';
type FieldPart = 'day' | 'month' | 'year';
type Side = 'left' | 'right';
type PickerType = 'month' | 'year';

interface MonthCell {
    day: number | null;
    date: Date | null;
    isToday: boolean;
    isStart: boolean;
    isEnd: boolean;
    inRange: boolean;
}

@Component({
    selector: 'app-date-range-picker',
    standalone: true,
    imports: [CommonModule],
    templateUrl: './date-range-picker.component.html',
    styleUrls: ['./date-range-picker.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DateRangePickerComponent implements OnChanges {
    @Input() value: DateRangeFilter | null = null;
    @Input() activeColor = '#685fff';
    @Output() apply = new EventEmitter<DateRangeFilter>();
    @Output() clear = new EventEmitter<void>();

    readonly weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    readonly monthNames = MONTH_NAMES;

    viewDate = signal<Date>(this.firstOfMonth(new Date()));
    rangeStart = signal<Date | null>(null);
    rangeEnd = signal<Date | null>(null);
    startDay = signal('');
    startMonth = signal('');
    startYear = signal('');
    endDay = signal('');
    endMonth = signal('');
    endYear = signal('');

    activePicker = signal<{ side: Side; type: PickerType } | null>(null);

    leftMonthIndex = computed(() => this.viewDate().getMonth());
    leftYear = computed(() => this.viewDate().getFullYear());
    rightMonthIndex = computed(() => this.nextMonth(this.viewDate()).getMonth());
    rightYear = computed(() => this.nextMonth(this.viewDate()).getFullYear());

    leftMonthName = computed(() => MONTH_NAMES[this.leftMonthIndex()]);
    rightMonthName = computed(() => MONTH_NAMES[this.rightMonthIndex()]);

    leftCells = computed<MonthCell[]>(() => this.buildMonthCells(this.viewDate(), this.rangeStart(), this.rangeEnd()));
    rightCells = computed<MonthCell[]>(() =>
        this.buildMonthCells(this.nextMonth(this.viewDate()), this.rangeStart(), this.rangeEnd())
    );

    @ViewChildren('digitInput') private digitInputs!: QueryList<ElementRef<HTMLInputElement>>;

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['value']) {
            const start = this.value?.after ? new Date(this.value.after) : null;
            const end = this.value?.before ? new Date(this.value.before) : null;
            this.rangeStart.set(start);
            this.rangeEnd.set(end);
            this.syncManualInputsFromRange();
            this.viewDate.set(this.firstOfMonth(start ?? new Date()));
        }
    }

    selectDay(date: Date | null): void {
        if (!date) return;
        const start = this.rangeStart();
        const end = this.rangeEnd();

        if (!start || (start && end)) {
            this.rangeStart.set(date);
            this.rangeEnd.set(null);
        } else if (date.getTime() < start.getTime()) {
            this.rangeStart.set(date);
            this.rangeEnd.set(start);
        } else {
            this.rangeEnd.set(date);
        }
        this.syncManualInputsFromRange();
    }

    prevPair(): void {
        const d = this.viewDate();
        this.viewDate.set(new Date(d.getFullYear(), d.getMonth() - 1, 1));
    }

    nextPair(): void {
        const d = this.viewDate();
        this.viewDate.set(new Date(d.getFullYear(), d.getMonth() + 1, 1));
    }

    toggleMonthPicker(side: Side, event: Event): void {
        event.stopPropagation();
        this.toggle(side, 'month');
    }

    toggleYearPicker(side: Side, event: Event): void {
        event.stopPropagation();
        this.toggle(side, 'year');
    }

    pickMonth(side: Side, monthIndex: number): void {
        if (side === 'left') {
            this.viewDate.set(new Date(this.leftYear(), monthIndex, 1));
        } else {
            const newRight = new Date(this.rightYear(), monthIndex, 1);
            this.viewDate.set(new Date(newRight.getFullYear(), newRight.getMonth() - 1, 1));
        }
        this.activePicker.set(null);
    }

    pickYear(side: Side, year: number): void {
        if (side === 'left') {
            this.viewDate.set(new Date(year, this.leftMonthIndex(), 1));
        } else {
            const newRight = new Date(year, this.rightMonthIndex(), 1);
            this.viewDate.set(new Date(newRight.getFullYear(), newRight.getMonth() - 1, 1));
        }
        this.activePicker.set(null);
    }

    yearOptions(side: Side): number[] {
        const year = side === 'left' ? this.leftYear() : this.rightYear();
        return Array.from({ length: 12 }, (_, i) => year - 5 + i);
    }

    closePickers(): void {
        this.activePicker.set(null);
    }

    private toggle(side: Side, type: PickerType): void {
        const current = this.activePicker();
        this.activePicker.set(current?.side === side && current.type === type ? null : { side, type });
    }

    onDigitInput(group: FieldGroup, part: FieldPart, raw: string, index: number): void {
        const maxLen = part === 'year' ? 4 : 2;
        const digits = raw.replace(/\D/g, '').slice(0, maxLen);
        this.fieldSignal(group, part).set(digits);

        if (digits.length === maxLen) {
            const inputs = this.digitInputs.toArray();
            inputs[index + 1]?.nativeElement.focus();
        }

        this.tryCommitGroup(group);
    }

    applyPreset(preset: 'today' | 'last7' | 'thisMonth'): void {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        let start: Date;
        let end: Date;

        if (preset === 'today') {
            start = today;
            end = today;
        } else if (preset === 'last7') {
            start = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 6);
            end = today;
        } else {
            start = new Date(today.getFullYear(), today.getMonth(), 1);
            end = today;
        }

        this.rangeStart.set(start);
        this.rangeEnd.set(end);
        this.syncManualInputsFromRange();
        this.viewDate.set(this.firstOfMonth(start));
        this.commit(start, end);
    }

    onSelect(): void {
        const start = this.rangeStart();
        if (!start) return;
        this.commit(start, this.rangeEnd() ?? start);
    }

    onClear(): void {
        this.rangeStart.set(null);
        this.rangeEnd.set(null);
        this.syncManualInputsFromRange();
        this.clear.emit();
    }

    private commit(start: Date, end: Date): void {
        this.apply.emit({
            after: this.startOfDayIso(start),
            before: this.endOfDayIso(end),
        });
    }

    private tryCommitGroup(group: FieldGroup): void {
        const day = parseInt(this.fieldSignal(group, 'day')(), 10);
        const month = parseInt(this.fieldSignal(group, 'month')(), 10);
        const year = parseInt(this.fieldSignal(group, 'year')(), 10);
        if (!day || !month || year < 1000) return;

        const date = new Date(year, month - 1, day);
        if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return;

        if (group === 'start') {
            this.rangeStart.set(date);
            if (this.rangeEnd() && date.getTime() > this.rangeEnd()!.getTime()) this.rangeEnd.set(null);
        } else {
            this.rangeEnd.set(date);
            if (this.rangeStart() && date.getTime() < this.rangeStart()!.getTime()) this.rangeStart.set(date);
        }
        this.viewDate.set(this.firstOfMonth(date));
    }

    private syncManualInputsFromRange(): void {
        const start = this.rangeStart();
        const end = this.rangeEnd();
        this.startDay.set(start ? String(start.getDate()).padStart(2, '0') : '');
        this.startMonth.set(start ? String(start.getMonth() + 1).padStart(2, '0') : '');
        this.startYear.set(start ? String(start.getFullYear()) : '');
        this.endDay.set(end ? String(end.getDate()).padStart(2, '0') : '');
        this.endMonth.set(end ? String(end.getMonth() + 1).padStart(2, '0') : '');
        this.endYear.set(end ? String(end.getFullYear()) : '');
    }

    private fieldSignal(group: FieldGroup, part: FieldPart) {
        return this[
            `${group}${part[0].toUpperCase()}${part.slice(1)}` as
                | 'startDay'
                | 'startMonth'
                | 'startYear'
                | 'endDay'
                | 'endMonth'
                | 'endYear'
        ];
    }

    private sameDay(a: Date, b: Date): boolean {
        return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    }

    private buildMonthCells(view: Date, start: Date | null, end: Date | null): MonthCell[] {
        const year = view.getFullYear();
        const month = view.getMonth();
        const todayMidnight = new Date();
        todayMidnight.setHours(0, 0, 0, 0);

        const leadingEmpties = new Date(year, month, 1).getDay();
        const daysInMonth = new Date(year, month + 1, 0).getDate();

        const cells: MonthCell[] = [];
        for (let i = 0; i < leadingEmpties; i++) {
            cells.push({ day: null, date: null, isToday: false, isStart: false, isEnd: false, inRange: false });
        }

        for (let d = 1; d <= daysInMonth; d++) {
            const date = new Date(year, month, d);
            const isStart = !!start && this.sameDay(date, start);
            const isEnd = !!end && this.sameDay(date, end);
            const inRange = !!start && !!end && date.getTime() > start.getTime() && date.getTime() < end.getTime();
            cells.push({
                day: d,
                date,
                isToday: this.sameDay(date, todayMidnight),
                isStart,
                isEnd,
                inRange,
            });
        }

        return cells;
    }

    private firstOfMonth(d: Date): Date {
        return new Date(d.getFullYear(), d.getMonth(), 1);
    }

    private nextMonth(d: Date): Date {
        return new Date(d.getFullYear(), d.getMonth() + 1, 1);
    }

    private startOfDayIso(d: Date): string {
        return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0, 0).toISOString();
    }

    private endOfDayIso(d: Date): string {
        return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 23, 59, 59, 999).toISOString();
    }
}
