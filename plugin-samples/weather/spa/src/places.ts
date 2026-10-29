import {
    addPlace,
    type ApiFailure,
    type ApiFetch,
    describeFailure,
    listPlaces,
    MAX_PLACE_QUERY_LENGTH,
    type PlaceCandidate,
    removePlace,
    type SavedPlace,
    searchPlaces,
} from './api';
import { conditionsText } from './conditions';
import { button, element } from './dom';
import { forecastAddress } from './forecast';
import type { Permissions } from './org-settings';

export const PLACES_PATH = '/places';

/** The permission Weather asks for before it lets a person add or remove places; EpicStaff calls it Edit. */
export const PLACES_EDIT_PERMISSION = 'update';

type SavedList =
    | { status: 'loading' }
    | { status: 'loaded'; places: readonly SavedPlace[] }
    | { status: 'failed'; message: string };

type Search =
    | { status: 'idle' }
    | { status: 'searching'; query: string }
    | { status: 'found'; query: string; results: readonly PlaceCandidate[] }
    | { status: 'failed'; query: string; message: string };

interface SavedRow {
    label: string;
    item: HTMLLIElement;
    /** "12.4 °C · 5 min ago", brought up to date on every render. */
    conditions: HTMLSpanElement;
    removeButton: HTMLButtonElement;
}

interface ResultRow {
    place: PlaceCandidate;
    label: string;
    item: HTMLLIElement;
    addButton: HTMLButtonElement;
}

/**
 * The Places page: the organization's saved places, in the backend's order, each with its current temperature and a
 * link to its forecast, and a search to add more.
 * Everyone who may open Weather sees the list; adding and removing need the Edit permission, which the backend checks
 * as well. After every change the page asks for the list again, so it shows the backend's list in the backend's order.
 * A saved place keeps its row while it is listed, and busy buttons are marked rather than disabled, so a re-render never
 * takes the focus.
 */
export class PlacesPage {
    readonly root = element('section', 'page');

    private readonly listHeading = element('h2', 'section-title', 'Saved places');
    /** Loading, no places yet, or why the list could not be loaded. */
    private readonly listNote = element('p', 'muted');
    private readonly list = element('ul', 'places');
    /** Shown after a failed load. */
    private readonly checkAgainButton = button('Check again', () => this.checkAgain());
    /** Why the last add or remove did not work. */
    private readonly actionMessage = element('p', 'note note--error');
    /** Why the person cannot add or remove places. */
    private readonly editNote = element('p', 'muted');
    private readonly searchSection = element('div', 'page');
    private readonly queryInput = element('input', 'input');
    private readonly searchButton = element('button', 'button', 'Search');
    /** What the search found, or why it found nothing; announced politely. */
    private readonly searchNote = element('p', 'muted');
    private readonly results = element('ul', 'places');
    private readonly savedRows = new Map<number, SavedRow>();
    private resultRows: ResultRow[] = [];
    private savedList: SavedList = { status: 'loading' };
    private search: Search = { status: 'idle' };
    /** The search the results show, so an unchanged search keeps its rows. */
    private shownSearch: Search | null = null;
    /** The places being added, by {@link placeKey}. */
    private readonly adding = new Set<string>();
    /** The places being removed, by id. */
    private readonly removing = new Set<number>();
    private actionError: string | null = null;
    private mayEdit = false;
    private loadRequested = false;
    /** Counts the list requests, so an older answer never replaces a newer one. */
    private listRequests = 0;

    constructor(
        private readonly fetchApi: ApiFetch,
        private readonly pluginName: string,
        private readonly onChange: () => void
    ) {
        // Takes the focus when the place whose Remove button had it leaves the list.
        this.listHeading.tabIndex = -1;
        this.checkAgainButton.classList.add('button--secondary');
        this.actionMessage.setAttribute('role', 'alert');

        const form = element('form', 'form form--inline');
        const label = element('label', 'field');
        this.queryInput.name = 'q';
        this.queryInput.required = true;
        this.queryInput.maxLength = MAX_PLACE_QUERY_LENGTH;
        this.queryInput.placeholder = 'Lisbon';
        this.queryInput.autocomplete = 'off';
        label.append(element('span', 'field-label', 'Place name'), this.queryInput);
        this.searchButton.type = 'submit';
        form.append(label, this.searchButton);
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            this.requestSearch();
        });
        this.searchNote.setAttribute('aria-live', 'polite');
        this.searchSection.append(element('h2', 'section-title', 'Add a place'), form, this.searchNote, this.results);

        this.root.append(
            this.listHeading,
            this.listNote,
            this.checkAgainButton,
            this.list,
            this.actionMessage,
            this.editNote,
            this.searchSection
        );
    }

    /** Asks for the list again, as after Weather was updated. */
    refresh(): void {
        this.checkAgain();
    }

    /** Brings the page up to date for what the person may do; asks for the list once. */
    update(permissions: Permissions): void {
        if (!this.loadRequested) {
            this.loadRequested = true;
            void this.load();
        }
        this.mayEdit = permissions.status === 'known' && permissions.actions.includes(PLACES_EDIT_PERMISSION);
        this.updateList();
        setText(this.actionMessage, this.actionError ?? '');
        this.actionMessage.hidden = this.actionError === null;
        this.updateEditNote(permissions);
        this.searchSection.hidden = !this.mayEdit;
        if (this.mayEdit) this.updateSearch();
    }

    private async load(): Promise<void> {
        await this.refreshList();
        this.onChange();
    }

    /** Asks for the list; drops the answer when a newer request was made meanwhile. */
    private async refreshList(): Promise<void> {
        const request = ++this.listRequests;
        const result = await listPlaces(this.fetchApi);
        if (request !== this.listRequests) return;
        this.savedList = result.ok
            ? { status: 'loaded', places: result.value }
            : { status: 'failed', message: `Could not load the places. ${describeFailure(result, this.pluginName)}` };
    }

    private checkAgain(): void {
        this.savedList = { status: 'loading' };
        this.onChange();
        void this.load();
    }

    private async add(place: PlaceCandidate): Promise<void> {
        const key = placeKey(place);
        if (this.adding.has(key) || this.isSaved(place)) return;
        this.adding.add(key);
        this.actionError = null;
        this.onChange();
        const result = await addPlace(this.fetchApi, place);
        // Saved already, perhaps by someone else: the list asked for below has it.
        if (!result.ok && result.code !== 'already_saved') {
            this.actionError = this.actionFailure(`add ${placeLabel(place)}`, result);
        }
        await this.refreshList();
        this.adding.delete(key);
        this.onChange();
    }

    private async remove(place: SavedPlace): Promise<void> {
        if (this.removing.has(place.id)) return;
        this.removing.add(place.id);
        this.actionError = null;
        this.onChange();
        const result = await removePlace(this.fetchApi, place.id);
        // Removed already, perhaps by someone else: the list asked for below no longer has it.
        if (!result.ok && result.code !== 'not_found') {
            this.actionError = this.actionFailure(`remove ${placeLabel(place)}`, result);
        }
        await this.refreshList();
        this.removing.delete(place.id);
        const hadFocus = this.savedRows.get(place.id)?.item.contains(document.activeElement) ?? false;
        this.onChange();
        if (hadFocus && !this.savedRows.has(place.id)) this.listHeading.focus();
    }

    private requestSearch(): void {
        const query = this.queryInput.value.trim();
        if (query.length === 0 || this.search.status === 'searching') return;
        this.search = { status: 'searching', query };
        this.onChange();
        void this.find(query);
    }

    /** One search at a time: the form ignores a new one while this runs. */
    private async find(query: string): Promise<void> {
        const result = await searchPlaces(this.fetchApi, query);
        this.search = result.ok
            ? { status: 'found', query, results: result.value }
            : { status: 'failed', query, message: this.searchFailure(query, result) };
        this.onChange();
    }

    private updateList(): void {
        const list = this.savedList;
        this.checkAgainButton.hidden = list.status !== 'failed';
        switch (list.status) {
            case 'loading':
                setNote(this.listNote, 'Loading the places…', false);
                break;
            case 'failed':
                setNote(this.listNote, list.message, true);
                break;
            case 'loaded':
                setNote(this.listNote, list.places.length === 0 ? 'No places saved yet.' : '', false);
                break;
        }
        const places = list.status === 'loaded' ? list.places : [];
        const listed = new Set(places.map((place) => place.id));
        for (const id of this.savedRows.keys()) {
            if (!listed.has(id)) this.savedRows.delete(id);
        }
        placeChildren(
            this.list,
            places.map((place) => this.savedRow(place))
        );
        this.list.hidden = places.length === 0;
    }

    /** The place's row, built the first time it is listed, with its Remove button brought up to date. */
    private savedRow(place: SavedPlace): HTMLLIElement {
        let row = this.savedRows.get(place.id);
        if (row === undefined) {
            const label = placeLabel(place);
            const forecast = element('a', 'button button--secondary', 'Forecast');
            forecast.href = forecastAddress(place.name);
            forecast.setAttribute('aria-label', `Forecast for ${label}`);
            const removeButton = button('Remove', () => void this.remove(place));
            removeButton.classList.add('button--secondary');
            const actions = element('div', 'actions');
            actions.append(forecast, removeButton);
            const conditions = element('span', 'muted');
            const text = element('div', 'place__text');
            text.append(element('span', null, label), conditions);
            const item = element('li', 'place');
            item.append(text, actions);
            row = { label, item, conditions, removeButton };
            this.savedRows.set(place.id, row);
        }
        setText(row.conditions, conditionsText(place.conditions, Date.now()));
        const removing = this.removing.has(place.id);
        row.removeButton.hidden = !this.mayEdit;
        setText(row.removeButton, removing ? 'Removing…' : 'Remove');
        row.removeButton.setAttribute('aria-label', `${removing ? 'Removing' : 'Remove'} ${row.label}`);
        row.removeButton.setAttribute('aria-disabled', String(removing));
        return row.item;
    }

    private updateEditNote(permissions: Permissions): void {
        let note = '';
        if (permissions.status === 'failed') {
            note = `Could not check your permissions, so adding and removing places is off: ${permissions.message}`;
        } else if (permissions.status === 'known' && !this.mayEdit) {
            note = `Adding and removing places needs the Edit permission on ${this.pluginName}.`;
        }
        setText(this.editNote, note);
        this.editNote.hidden = note === '';
    }

    private updateSearch(): void {
        const searching = this.search.status === 'searching';
        // Read-only rather than disabled while searching: disabling the focused field or button drops the focus.
        this.queryInput.readOnly = searching;
        this.searchButton.setAttribute('aria-disabled', String(searching));
        setNote(this.searchNote, this.searchNoteText(), this.search.status === 'failed');
        if (this.shownSearch !== this.search) {
            this.shownSearch = this.search;
            this.resultRows =
                this.search.status === 'found' ? this.search.results.map((place) => this.resultRow(place)) : [];
            this.results.replaceChildren(...this.resultRows.map((row) => row.item));
        }
        this.results.hidden = this.resultRows.length === 0;
        for (const row of this.resultRows) this.updateResultRow(row);
    }

    private searchNoteText(): string {
        switch (this.search.status) {
            case 'idle':
                return '';
            case 'searching':
                return `Looking up “${this.search.query}”…`;
            case 'failed':
                return this.search.message;
            case 'found': {
                const count = this.search.results.length;
                if (count === 0) return `No place called “${this.search.query}” found.`;
                return `${count} ${count === 1 ? 'place matches' : 'places match'} “${this.search.query}”.`;
            }
        }
    }

    private resultRow(place: PlaceCandidate): ResultRow {
        const label = placeLabel(place);
        const addButton = button('Add', () => void this.add(place));
        const item = element('li', 'place');
        item.append(element('span', null, label), addButton);
        return { place, label, item, addButton };
    }

    private updateResultRow(row: ResultRow): void {
        const { addButton, label, place } = row;
        if (this.isSaved(place)) {
            setText(addButton, 'Saved');
            addButton.setAttribute('aria-label', `${label} is saved`);
            addButton.setAttribute('aria-disabled', 'true');
        } else if (this.adding.has(placeKey(place))) {
            setText(addButton, 'Adding…');
            addButton.setAttribute('aria-label', `Adding ${label}`);
            addButton.setAttribute('aria-disabled', 'true');
        } else {
            setText(addButton, 'Add');
            addButton.setAttribute('aria-label', `Add ${label}`);
            addButton.setAttribute('aria-disabled', 'false');
        }
    }

    /** True when the list holds a place with this name, region and country, which the backend would refuse. */
    private isSaved(place: PlaceCandidate): boolean {
        if (this.savedList.status !== 'loaded') return false;
        const key = placeKey(place);
        return this.savedList.places.some((saved) => placeKey(saved) === key);
    }

    private searchFailure(query: string, failure: ApiFailure<'invalid_request' | 'lookup_failed'>): string {
        switch (failure.code) {
            case 'invalid_request':
                return `Enter a place name of at most ${MAX_PLACE_QUERY_LENGTH} characters.`;
            case 'lookup_failed':
                return `Could not look up “${query}” at Open-Meteo. Try again in a minute.`;
            default:
                return describeFailure(failure, this.pluginName);
        }
    }

    private actionFailure(action: string, failure: ApiFailure<string>): string {
        if (failure.code === 'forbidden') {
            return `You need the Edit permission on ${this.pluginName} to add or remove places.`;
        }
        return `Could not ${action}. ${describeFailure(failure, this.pluginName)}`;
    }
}

/**
 * How the page names a place: "Springfield, Illinois, United States". The region is left out when the search knows
 * none, and when it only repeats the name: "Lisbon, Portugal".
 */
function placeLabel(place: PlaceCandidate): string {
    const region = place.admin1;
    const parts =
        region === null || region === '' || region === place.name
            ? [place.name, place.country]
            : [place.name, region, place.country];
    return parts.join(', ');
}

/** What tells two places apart for the backend: their name, region and country. */
function placeKey(place: PlaceCandidate): string {
    return JSON.stringify([place.name, place.admin1, place.country]);
}

/**
 * Makes `children` the children of `parent`, in order. Rows that stay are not moved, so one holding the focus keeps it.
 */
function placeChildren(parent: HTMLElement, children: readonly HTMLElement[]): void {
    const wanted = new Set<Element>(children);
    for (const child of Array.from(parent.children)) {
        if (!wanted.has(child)) child.remove();
    }
    children.forEach((child, index) => {
        const current = parent.children[index] ?? null;
        if (current !== child) parent.insertBefore(child, current);
    });
}

/** Changes the text only when it changes, so a live region does not announce it again on every render. */
function setText(node: HTMLElement, text: string): void {
    if (node.textContent !== text) node.textContent = text;
}

/** Shows `text` as a muted line or an error note; hides the line when there is nothing to say. */
function setNote(node: HTMLElement, text: string, isError: boolean): void {
    setText(node, text);
    node.className = isError ? 'note note--error' : 'muted';
    node.hidden = text === '';
}
