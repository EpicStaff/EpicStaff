import {
    type ApiFetch,
    describeFailure,
    getOrgSettings,
    listLlmModels,
    type LlmConfigRef,
    type LlmModel,
    MAX_API_KEY_LENGTH,
    saveLlmSettings,
} from './api';
import { button, element } from './dom';

export const ORG_SETTINGS_PATH = '/org-settings';

/** The permission Weather asks for before it lets a person change its organization settings. */
export const ORG_SETTINGS_PERMISSION = 'delete';

/** What the person may do in the plugin, from `GET /api/whoami`. */
export type Permissions =
    | { status: 'loading' }
    | { status: 'known'; actions: readonly string[] }
    | { status: 'failed'; message: string };

type Settings =
    | { status: 'loading' }
    | { status: 'forbidden' }
    | { status: 'configured'; config: LlmConfigRef }
    | { status: 'form'; models: LlmModel[] }
    | { status: 'failed'; message: string };

/**
 * The Organization settings page: the model and key Weather writes its summaries with. Saving makes EpicStaff store
 * the key as a secret and create an LLM config, both on behalf of the person. Weather itself checks the Delete
 * permission; without it the page says so. The form, the note and "Check again" are built once, so a re-render never
 * takes the typed key or the focus, and the key leaves the page as soon as the backend answered.
 */
export class OrgSettingsPage {
    readonly root = element('section', 'page');

    private readonly intro = element('p', 'muted');
    private readonly body = element('div', 'page');
    private readonly form = element('form', 'form');
    private readonly modelSelect = element('select', 'input');
    private readonly keyInput = element('input', 'input');
    private readonly saveButton = element('button', 'button', 'Save');
    private readonly formMessage = element('p', 'note note--error');
    /** What the page says instead of the form: no permission, or why the settings could not be loaded. */
    private readonly note = element('p', 'note');
    /** Shown after a failed load. */
    private readonly checkAgainButton = button('Check again', () => this.checkAgain());
    private settings: Settings = { status: 'loading' };
    private saving = false;
    private formError: string | null = null;
    private loadRequested = false;
    private shownModels: LlmModel[] | null = null;

    constructor(
        private readonly fetchApi: ApiFetch,
        private readonly pluginName: string,
        private readonly onChange: () => void
    ) {
        this.modelSelect.name = 'llm_model_id';
        this.modelSelect.required = true;
        this.keyInput.name = 'api_key';
        this.keyInput.type = 'password';
        this.keyInput.required = true;
        this.keyInput.maxLength = MAX_API_KEY_LENGTH;
        // Keeps the browser from offering a saved password for a provider's key.
        this.keyInput.autocomplete = 'new-password';
        this.saveButton.type = 'submit';
        this.formMessage.setAttribute('role', 'alert');
        this.form.append(
            field('Model', this.modelSelect),
            field('API key', this.keyInput),
            this.formMessage,
            this.saveButton
        );
        this.form.addEventListener('submit', (event) => {
            event.preventDefault();
            void this.save();
        });
        this.checkAgainButton.classList.add('button--secondary');
        this.root.append(this.intro, this.body);
    }

    /** Brings the page up to date for what the person may do; loads the settings once they may see them. */
    update(permissions: Permissions): void {
        if (permissions.status === 'loading') {
            this.show('Checking your permissions…', []);
            return;
        }
        if (permissions.status === 'failed') {
            this.setNote(`Could not check your permissions: ${permissions.message}`, true);
            this.show('', [this.note]);
            return;
        }
        if (!permissions.actions.includes(ORG_SETTINGS_PERMISSION) || this.settings.status === 'forbidden') {
            this.setNote(
                `You need the Delete permission on ${this.pluginName} to change its organization settings.`,
                false
            );
            this.show('', [this.note]);
            return;
        }
        if (!this.loadRequested) {
            this.loadRequested = true;
            void this.load();
        }
        switch (this.settings.status) {
            case 'loading':
                this.show('Loading the settings…', []);
                return;
            case 'failed':
                this.setNote(this.settings.message, true);
                this.show('', [this.note, this.checkAgainButton]);
                return;
            case 'configured':
                this.show(
                    `${this.pluginName} writes its summaries with the LLM config ` +
                        `“${this.settings.config.name}” in this organization.`,
                    []
                );
                return;
            case 'form':
                this.showForm(this.settings.models);
                return;
        }
    }

    private async load(): Promise<void> {
        const current = await getOrgSettings(this.fetchApi);
        if (!current.ok) {
            this.settings =
                current.code === 'forbidden'
                    ? { status: 'forbidden' }
                    : { status: 'failed', message: describeFailure(current, this.pluginName) };
        } else if (current.value !== null) {
            this.settings = { status: 'configured', config: current.value };
        } else {
            const models = await listLlmModels(this.fetchApi);
            if (models.ok) this.settings = { status: 'form', models: models.value };
            else if (models.code === 'forbidden') this.settings = { status: 'forbidden' };
            else this.settings = { status: 'failed', message: describeFailure(models, this.pluginName) };
        }
        this.onChange();
    }

    private async save(): Promise<void> {
        if (this.saving || this.settings.status !== 'form') return;
        const modelId = Number(this.modelSelect.value);
        const apiKey = this.keyInput.value;
        if (!Number.isInteger(modelId) || modelId <= 0 || apiKey.length === 0) {
            this.formError = 'Pick a model and enter its API key.';
            this.onChange();
            return;
        }
        this.saving = true;
        this.formError = null;
        this.onChange();
        const result = await saveLlmSettings(this.fetchApi, modelId, apiKey);
        this.saving = false;
        // The key leaves the page with every answer; trying again means typing it again.
        this.keyInput.value = '';
        if (result.ok) {
            this.settings = { status: 'configured', config: result.value };
        } else {
            switch (result.code) {
                case 'already_configured':
                    // Someone else set it up meanwhile: show theirs.
                    this.settings = { status: 'loading' };
                    this.loadRequested = false;
                    break;
                case 'forbidden':
                    // Only people with Delete on the plugin get the form, so this refusal means the person lacks
                    // EpicStaff's own permissions to create the secret and the LLM config.
                    this.formError = 'You need permission to create secrets and LLM configs in EpicStaff.';
                    break;
                case 'secret_exists':
                    // The backend's message names the secret and says how to clear the way.
                    this.formError = result.message || 'A secret with that name already exists in EpicStaff.';
                    break;
                case 'invalid_request':
                    this.formError =
                        `${this.pluginName} did not take that. Pick a model and enter a key of at most ` +
                        `${MAX_API_KEY_LENGTH} characters.`;
                    break;
                default:
                    this.formError = describeFailure(result, this.pluginName);
                    break;
            }
        }
        this.onChange();
    }

    private showForm(models: LlmModel[]): void {
        if (this.shownModels !== models) {
            this.shownModels = models;
            const placeholder = element(
                'option',
                null,
                models.length > 0 ? 'Choose a model' : 'EpicStaff lists no model'
            );
            placeholder.value = '';
            placeholder.disabled = true;
            placeholder.selected = true;
            this.modelSelect.replaceChildren(
                placeholder,
                ...models.map((model) => {
                    const option = element('option', null, model.name);
                    option.value = String(model.id);
                    return option;
                })
            );
        }
        // Read-only rather than disabled while saving: disabling the focused field or button drops the focus.
        this.modelSelect.disabled = this.saving;
        this.keyInput.readOnly = this.saving;
        this.saveButton.disabled = models.length === 0;
        this.saveButton.setAttribute('aria-disabled', String(this.saving));
        this.saveButton.textContent = this.saving ? 'Saving…' : 'Save';
        this.formMessage.hidden = this.formError === null;
        // Same text, same node: an alert is not announced again on every render.
        if (this.formMessage.textContent !== (this.formError ?? ''))
            this.formMessage.textContent = this.formError ?? '';
        this.show(
            `Pick the model ${this.pluginName} writes its summaries with and enter that provider's API key. ` +
                'EpicStaff stores the key as a secret of this organization and creates an LLM config with it, both ' +
                'on your behalf.',
            [this.form]
        );
    }

    /** Shows `intro` and `content`; leaves the body alone when it already holds exactly `content`. */
    private show(intro: string, content: HTMLElement[]): void {
        this.intro.textContent = intro;
        this.intro.hidden = intro === '';
        const current = Array.from(this.body.children);
        if (current.length !== content.length || current.some((child, index) => child !== content[index])) {
            this.body.replaceChildren(...content);
        }
    }

    /** Loads the settings again after a failure. */
    private checkAgain(): void {
        this.settings = { status: 'loading' };
        this.loadRequested = false;
        this.onChange();
    }

    /** Changes the note only when its text changes, so an alert is not announced again on every render. */
    private setNote(text: string, isError: boolean): void {
        if (this.note.textContent === text) return;
        this.note.textContent = text;
        this.note.className = isError ? 'note note--error' : 'note';
        if (isError) this.note.setAttribute('role', 'alert');
        else this.note.removeAttribute('role');
    }
}

function field(label: string, control: HTMLElement): HTMLLabelElement {
    const wrapper = element('label', 'field');
    wrapper.append(element('span', 'field-label', label), control);
    return wrapper;
}
