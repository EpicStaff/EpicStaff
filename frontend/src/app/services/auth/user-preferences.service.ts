import { HttpErrorResponse } from '@angular/common/http';
import { computed, DestroyRef, effect, inject, Injectable, Signal, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DEFAULT_USER_PREFERENCES, PreferenceSection, UserPreferences } from '@shared/models';
import { effectiveZone, extractHttpErrorMessage, humanizeErrorMessage } from '@shared/utils';
import { catchError, concatMap, EMPTY, groupBy, mergeMap, Observable, Subject, tap } from 'rxjs';

import { ToastService } from '../notifications';
import { ProfileService } from './profile.service';

/** Delay after the last change of a section before the section is saved. */
export const PREFERENCES_SAVE_DEBOUNCE_MS = 300;

type SectionValues = Readonly<Record<string, unknown>>;

/** Changes not confirmed by the server yet, shown on top of the profile's values. Bound to the user who made them. */
interface PendingChanges {
    readonly userId: number;
    readonly sections: Readonly<Partial<Record<PreferenceSection, SectionValues>>>;
}

/**
 * The signed-in user's preferences, saved optimistically. A change shows at once; each section is sent in one PATCH
 * once no newer change of it arrives within the debounce, and a section's PATCHes go out one at a time, in order.
 * Until its PATCH settles, a change stays on top of the profile, so a profile reload that lands mid-save does not
 * bring back the old value. A failed save drops the change, which shows the stored value again, and says why in a
 * toast. A change not sent yet is dropped when its user signs out or another user signs in. Lives at the root so a
 * change outlives the page it was made on.
 */
@Injectable({
    providedIn: 'root',
})
export class UserPreferencesService {
    private readonly profileService = inject(ProfileService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    private readonly pending = signal<PendingChanges | null>(null);
    private readonly effective = computed<UserPreferences>(() => {
        const user = this.profileService.currentUserSignal();
        const pending = this.pending();
        const pendingSections = pending !== null && pending.userId === user?.id ? pending.sections : {};
        // Every page reads the display timezone, so a profile that lacks the preferences must not break it: the
        // defaults stand in, as they do for a key the server does not send.
        const stored: Partial<UserPreferences> = user?.preferences ?? {};
        return {
            general: {
                ...DEFAULT_USER_PREFERENCES.general,
                ...stored.general,
                ...pendingSections.general,
            },
            flow_editor: {
                ...DEFAULT_USER_PREFERENCES.flow_editor,
                ...stored.flow_editor,
                ...pendingSections.flow_editor,
            },
        };
    });

    /** The IANA zone dates are shown in: the chosen display timezone, or the browser's while none is chosen. */
    readonly displayZone: Signal<string> = computed(() => effectiveZone(this.effective().general.display_timezone));

    /** Changes still waiting out their debounce, per section. Moved to a PATCH when the section is sent. */
    private readonly unsent = new Map<PreferenceSection, SectionValues>();
    private readonly debounceTimers = new Map<PreferenceSection, ReturnType<typeof setTimeout>>();
    private readonly dueSections = new Subject<PreferenceSection>();

    constructor() {
        // A change not sent when its user signed out is dropped with its timer, so it neither shows nor gets saved when
        // that user signs back in: the profile then holds what the server stores.
        effect(() => {
            const userId = this.profileService.currentUserSignal()?.id;
            const pending = untracked(this.pending);
            if (pending !== null && pending.userId !== userId) this.forgetPendingChanges();
        });
        this.dueSections
            .pipe(
                groupBy((section) => section),
                mergeMap((sectionSends) => sectionSends.pipe(concatMap((section) => this.send(section)))),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
        this.destroyRef.onDestroy(() => this.debounceTimers.forEach((timer) => clearTimeout(timer)));
    }

    section<S extends PreferenceSection>(name: S): Signal<UserPreferences[S]> {
        return computed(() => this.effective()[name]);
    }

    /** Applies `change` to the section at once and saves it after the debounce. Ignored when nobody is signed in. */
    patchSection<S extends PreferenceSection>(name: S, change: Partial<UserPreferences[S]>): void {
        const userId = this.profileService.currentUserSignal()?.id;
        if (userId === undefined) return;
        const values = definedValues(change);

        // Another user signed in, and the effect has not dropped the previous one's changes yet.
        if (this.pending()?.userId !== userId) this.forgetPendingChanges();
        const sections = this.pending()?.sections ?? {};
        this.pending.set({ userId, sections: { ...sections, [name]: { ...sections[name], ...values } } });
        this.unsent.set(name, { ...this.unsent.get(name), ...values });

        clearTimeout(this.debounceTimers.get(name));
        this.debounceTimers.set(
            name,
            setTimeout(() => {
                this.debounceTimers.delete(name);
                this.dueSections.next(name);
            }, PREFERENCES_SAVE_DEBOUNCE_MS)
        );
    }

    private forgetPendingChanges(): void {
        this.debounceTimers.forEach((timer) => clearTimeout(timer));
        this.debounceTimers.clear();
        this.unsent.clear();
        this.pending.set(null);
    }

    private send(section: PreferenceSection): Observable<unknown> {
        const change = this.unsent.get(section);
        this.unsent.delete(section);
        const userId = this.pending()?.userId;
        if (change === undefined || userId === undefined || userId !== this.profileService.currentUserSignal()?.id) {
            return EMPTY;
        }

        return this.profileService.updatePreferencesSection(section, change).pipe(
            tap(() => this.settle(userId, section, change)),
            catchError((error: HttpErrorResponse) => {
                this.settle(userId, section, change);
                const reason = humanizeErrorMessage(extractHttpErrorMessage(error, ''));
                this.toastService.error(
                    reason ? `Could not save the setting: ${reason}` : 'Could not save the setting'
                );
                return EMPTY;
            })
        );
    }

    /** Drops the sent values from the pending changes, except those changed again since they were sent. */
    private settle(userId: number, section: PreferenceSection, sent: SectionValues): void {
        const pending = this.pending();
        if (pending === null || pending.userId !== userId) return;
        const unsent = this.unsent.get(section) ?? {};
        const remaining = Object.fromEntries(
            Object.entries(pending.sections[section] ?? {}).filter(
                ([key, value]) => key in unsent || !Object.is(value, sent[key])
            )
        );
        this.pending.set({ userId, sections: { ...pending.sections, [section]: remaining } });
    }
}

function definedValues(change: object): SectionValues {
    return Object.fromEntries(Object.entries(change).filter(([, value]) => value !== undefined));
}
