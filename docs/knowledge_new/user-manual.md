# Knowledge Bases (RAG) — User Manual

This guide explains how to work with knowledge bases in EpicStaff through the interface: how to
create a collection, upload documents, configure retrieval (RAG), and connect knowledge to an agent.

Button, field, and tab names are shown exactly as they appear in the UI, in `monospace` or quotes,
so you can find them on screen.

---

## 1. Core concepts

Four terms are used throughout this guide.

- **Collection** — your knowledge base: a set of documents on one topic plus the search settings for
  them. For example, "Product documentation" or "Legal contracts". An agent searches for answers
  inside a collection.

- **Document** — a file uploaded into a collection. Supported formats are **PDF, CSV, MD, DOCX, TXT,
  JSON, HTML**. The maximum size of a single file is **20 MB**.

- **RAG** (Retrieval-Augmented Generation) — the method the system uses to find the relevant
  fragments of your documents for an agent's question. EpicStaff ships with two RAG types:
  **Naive RAG** (simple) and **Graph RAG** (advanced). The same set of files can be indexed with
  more than one RAG type.

- **Embedding** — a numeric representation of text that lets the system measure semantic similarity.
  Both your documents and the agent's question are turned into embeddings by a dedicated model
  (the **Embedder**), so search finds fragments that are closest in *meaning* to the question — not
  just fragments that share the same words.

**The overall flow:** you create a collection → upload files → choose a RAG type and an embedding
model → the system splits documents into fragments (chunks) and indexes them → you attach the
collection to an agent → at runtime the agent searches the collection for answers.

---

## 2. Creating a knowledge collection

Creation runs through a three-step wizard.

### Step 1 — "Upload Files"

- **`Collection Name`** — a unique collection name (required, up to **255** characters). It
  identifies the collection in the list and when attaching it to agents.
- **`Guidance for Agents`** — a collection description (up to **250** characters). This is more than
  a note: the agent reads it to **decide when to search this collection**. Be specific — what is
  inside and which questions it answers. Example: "Returns and warranty policy. Answers questions
  about return windows, warranty terms, and exchanges."
- **File upload** — drag files into the upload area or pick them manually. Above the area the allowed
  types are shown: `Allowed file types: PDF, CSV, MD, DOCX, TXT, JSON, HTML`. The `Selected Files: (N)`
  counter shows how many files are selected.

### Step 2 — "Select RAG Type"

This is where you choose the search strategy. Three cards are available:

| Card | Level | When to choose |
|---|---|---|
| **`Naive RAG`** | `Basic` (★) | Small collections, simple semantic search. Minimal settings. Start here. |
| **`Graph RAG`** | `Advanced` (★★) | Complex questions where relationships between entities (people, organizations, events) and broader context matter. |
| **`Hybrid RAG`** | `Expert` (★★★) | **Not available yet** — the card is disabled. |

Below the type selection is the **`AI Model Configuration`** block:

- **`Embedder`** — the embedding model that turns documents into vectors. Models differ in quality
  and speed. Selection is required.
- **`LLM Model`** — appears **only for Graph RAG**. The language model that builds the graph of
  entities and relationships during indexing.

> **Important:** the chosen embedding model is baked into the index. If you change the embedder later,
> the old and new vectors become incompatible and search starts returning garbage or empty results.
> After changing the embedder, re-index the collection (see section 8).

### Step 3 — "Configure"

The contents of this step depend on the chosen RAG type:

- chose **Naive RAG** → the chunk configuration table opens (section 3);
- chose **Graph RAG** → the index parameters panel opens (section 4).

After configuring, indexing starts — the system splits documents into chunks and computes embeddings.
You can follow the status right in the interface (section 8).

---

## 3. Configuring Naive RAG

Naive RAG splits each document into **chunks** (fragments) and finds the ones closest to the question.
The key setting is **how exactly a document is cut into chunks**. It can be set per file.

### Documents table

On the left is the list of uploaded files as a table with these columns:

- **`FILES`** — file name (filterable);
- **`CHUNK STRATEGY`** — chunking strategy (filterable);
- **`CHUNK SIZE`** — chunk size;
- **`OVERLAP`** — overlap between chunks;
- a status column and an actions column.

**Status filter** (dropdown above the table):

- **`Show All`** — all files;
- **`Issues`** — files with problems;
- **`Not indexed`** — not yet indexed;
- **`Indexed`** — indexed.

### Tuning a single file — the "Tune" button

The **`Tune`** button in a file row opens the detailed chunking dialog for that document. In the
dialog you can page through documents with previous/next buttons and see a **live chunk preview**
(`Chunk Preview`) — that is, exactly how the document will be split with the current parameters,
before indexing runs. The preview has a search-within-chunks box.

Chunking strategies and their parameters are described in detail in section 5.

### Bulk editing — "Bulk configuration"

To apply the same settings to several files at once:

1. Click **`Bulk configuration`** — a bulk-edit row appears along with checkboxes on the files.
2. Check the files you want.
3. In the row set the strategy, **`Chunk Size`**, and **`Overlap`**, then click **`Apply`**.

Value limits in bulk edit: **`Chunk Size`** — from **20** to **8000**, **`Overlap`** — from **0** to
**1000**. For the **CSV** strategy these two fields are unavailable (it has its own parameters — see
section 5).

### Other actions

- **`Re-include Files`** — restore files that were previously marked for deletion.
- The trash icon — delete the checked files (enabled once at least one file is checked).

---

## 4. Configuring Graph RAG

Graph RAG builds a **graph of entities and the relationships** between them, which helps answer more
complex questions. Unlike Naive RAG, parameters here are set **for the whole collection at once**
(a shared index), not per file. There is no live chunk preview for Graph RAG.

> Graph RAG works reliably mainly with text files. The interface warns:
> `Non-txt files may not be properly processed, resulting in empty search results.` For non-txt files
> the search result may end up empty.

### Index Mode

- **`Update new`** — index only new files, keeping the existing configuration. Faster; good for
  adding documents.
- **`Total re-index`** — re-index all files with the new configuration. Needed after changing index
  parameters.

### Index parameters

| Field | What it sets | Range / default |
|---|---|---|
| **`Chunk Strategy`** | How to split text: by tokens (`tokens`) or by sentences (`sentences`) | default `tokens` |
| **`Chunk Size`** | Maximum chunk size | 100–10000, default **1200** |
| **`Chunk Overlap`** | Overlap between chunks | 0–5000, default **100** |
| **`Entity Types`** | Entity types to recognize (entered as tags) | default `organization`, `person`, `geo`, `event` |
| **`Max Gleanings`** | How many "gleaning" passes over the text to run when extracting entities | 1–10, default **1** |
| **`Max Cluster Size`** | Maximum graph cluster size to export | 1–100, default **10** |

The **`Reset to Origin`** button returns all parameters to their defaults.

For fine tuning there is also a JSON editor for the index configuration — usually for advanced users;
for most tasks the form fields above are enough.

---

## 5. Chunking strategy reference

The strategy determines how a document is cut into chunks. The right strategy depends on the
document's **format and structure**. Below are all Naive RAG strategies and their parameters.

Two parameters appear almost everywhere:

- **`Chunk Size`** — the maximum chunk size. Smaller chunks are more precise but may lose context;
  larger chunks preserve more context but are less precise. (Range 20–8000.)
- **`Chunk Overlap`** — how many characters/tokens overlap between adjacent chunks. Helps avoid
  "cutting" a thought at a boundary. Must be **smaller** than the chunk size. (Range 0–1000.)

### Character
General-purpose splitting by character count. Good for plain text.
- `Chunk Size`, `Chunk Overlap`
- **`Regex`** *(additional)* — a regular-expression delimiter. Text is split wherever the pattern
  matches. Useful for custom delimiters or structured content.

### Token
Splitting by token count (the units a language model operates on). Closer to how the model "sees"
text.
- `Chunk Size`, `Chunk Overlap`

### CSV
Splits tabular data by rows. There is no `Chunk Size` / `Overlap` here.
- **`Rows In Chunk`** — how many CSV rows go into one chunk. More rows preserve more tabular context.
- **`Headers level`** — how many header rows to attach to each chunk, to preserve column names when
  splitting a large table.

### Markdown
Structure-aware Markdown splitting.
- `Chunk Size`, `Chunk Overlap`
- **`Headers to Split On`** *(additional)* — which header levels to split on:
  `# Header 1` … `###### Header 6`.
- **`Return Each Line`** *(additional, toggle)* — treat each line as a separate chunk. Handy for
  lists and structured content.
- **`Strip Headers`** *(additional, toggle)* — remove Markdown header syntax (`#`, `##`) from the
  content while keeping the text.

### JSON
Splitting of JSON documents.
- `Chunk Size`, `Chunk Overlap`

### HTML
Text extraction and splitting from HTML.
- `Chunk Size`, `Chunk Overlap`
- **`Preserve Links`** *(additional, toggle)* — keep hyperlinks in the text when links matter as
  context.
- **`Normalize Text`** *(additional, toggle)* — clean the text: remove extra whitespace, formatting
  artifacts, and HTML noise.
- **`External Metadata`** *(additional, JSON)* — extra metadata (a JSON object) attached to every
  chunk.
- **`Denylist Tags`** *(additional)* — HTML tags to exclude (e.g. `script`, `style`). Their content
  is removed before chunking.

**Quick pick:** plain text/PDF → **Character** or **Token**; tables → **CSV**; Markdown docs →
**Markdown**; web pages → **HTML**; structured data → **JSON**.

---

## 6. Managing a collection

Opening a collection takes you to its details page: the file list, the built RAGs, and collection
info.

**Collection-level actions:**
- The collection name can be edited directly in the header.
- The trash icon (`Delete collection`) — delete the entire collection (requires delete permission).

**Files section (`Collection Files`):**
- The `download` icon — download all files in the collection.
- The copy icon (`Copy files`) — copy files into another collection.
- The `plus` icon (`Add file`) — upload a new file (requires update permission).
- In each file row: `Preview` (eye icon), `Download`, `Remove file` (x icon).

**RAG section:** shows all RAGs built for the collection with their statuses. The "+" button builds a
new RAG or updates an existing one. A single collection can have both a Naive and a Graph RAG built —
you pick the one you want when attaching it to an agent.

---

## 7. Connecting knowledge to an agent

Knowledge is attached to an agent through the settings panel in the agent's surface card. This is
where you define **how** the agent searches the collection.

Steps:
1. Select one or more collections. If none are selected, the panel prompts:
   `Select at least one collection to configure retrieval settings.`
2. For each collection, choose a search method in the **`RAG`** field. Only RAGs that are **already
   built** for that collection are listed. If none exist, you'll see
   `No RAG has been built for this collection yet.`
3. Configure the search parameters — they depend on the RAG type and are **saved at the agent
   level**, not the collection level. So the same RAG can be tuned differently for different agents.

### Naive RAG settings

- **`Similarity Threshold`** — the semantic similarity threshold (0–1, step 0.1, default **0.2**).
  Lower returns more but less relevant results; higher is more precise but may miss useful info.
- **`Search Limit`** — the maximum number of fragments to return (1–1000, default **3**). More gives
  richer context but slower answers.

### Graph RAG settings

**`Search Type`** — the graph search method:

- **`Basic`** — vector search (like Naive RAG, but over the graph index).
- **`Local`** — combines data from the knowledge graph with text chunks of the source documents.
  Suited to questions about specific entities mentioned in the documents.
- **`Global`** and **`DRIFT`** — **not available yet** (`Not available yet`).

**`Basic` parameters:**
- **`Prompt`** — a custom general-knowledge instruction (up to 1000 characters). Empty = default.
- **`K`** — how many text units to retrieve from the vector store (1–100, step 5, default **10**).
- **`Max Context Tokens`** — the maximum context size in tokens (100–100000, step 100,
  default **12000**).

**`Local` parameters:**
- **`Prompt`** — a custom instruction (up to 1000 characters, empty = default).
- **`Text Unit Proportion`** — the proportion of text fragments in the context (0–1, step 0.01,
  default **0.5**).
- **`Community Proportion`** — the proportion of graph "community" data (0–1, step 0.01,
  default **0.15**).
- **`Conversation History Max Turns`** — how many recent dialog turns to include (1–50, default **5**).
- **`Top K Entities`** — how many most-relevant entities to take (1–100, step 5, default **10**).
- **`Top K Relationships`** — how many most-relevant relationships to take (1–100, step 5,
  default **10**).
- **`Max Context Tokens`** — the maximum context size in tokens (100–100000, step 100,
  default **12000**).

---

## 8. Statuses and troubleshooting

### What the statuses mean

Statuses appear on documents and on RAGs during and after indexing:

| Status | Meaning |
|---|---|
| **`New`** | The RAG was just created; indexing has not run yet. |
| **`Processing`** | Indexing is in progress (chunking + embeddings). Wait for it to finish. |
| **`Completed`** | Indexed successfully and ready for search. |
| **`Outdated`** | The configuration changed after indexing (tooltip `Indexed config outdated`). A re-index is needed. |
| **`Partial`** | Some documents were indexed, some were not. |
| **`Cancelled`** | Indexing was cancelled. |
| **`Failed`** | Indexing failed (tooltip `Indexing failed`). |

### Common situations

- **Search returns empty or garbage after changing the embedding model.** The old and new vectors are
  dimensionally incompatible. Fix: run a full re-index of the collection (for Graph RAG, use
  `Total re-index`).

- **`Outdated` status.** You changed chunking/index parameters but didn't re-index. Rebuild the RAG
  to apply the new settings.

- **Graph RAG finds nothing in non-txt files.** Graph RAG reliably processes text files; PDF/DOCX/HTML
  may yield empty results. Upload text versions of documents for Graph RAG.

- **`Failed` status.** Indexing failed. Check that the files are valid and under 20 MB, that a
  suitable chunking strategy is selected, and run indexing again. If it keeps failing, contact the
  team.

- **The agent doesn't search a collection even though it's attached.** Make sure `Guidance for Agents`
  clearly describes which questions the collection answers — the agent relies on this description to
  decide when to search. Also verify that a RAG is built for the collection and selected in the
  agent's `RAG` field.

- **Too few / too many results from the agent.** For Naive RAG, adjust `Similarity Threshold`
  (higher = stricter) and `Search Limit` (higher = broader context).
