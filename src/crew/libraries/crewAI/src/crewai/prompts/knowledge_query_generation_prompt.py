from textwrap import dedent

KNOWLEDGE_QUERY_GENERATION_PROMPT = dedent(
    """
    You are an assistant that generates one or more *knowledge queries* 
    for a retrieval-augmented generation (RAG) system.

    ### Context
    - **Role:** {role}
    - **Goal:** {goal}
    - **Backstory:** {backstory}
    - **Current task (PRIMARY SOURCE):** {description}
    - **Expected output:** {expected_output}
    {previous_context_block}

    ---
    ## INFORMATION PRIORITY (Critical for Reasoning)

    - **Current task** → This is the **single most authoritative and dominant source**.  
       The knowledge query **must** be based primarily and explicitly on its content.
    {previous_context_guidelines}
    - **Role, goal, backstory, expected output** →  
       These are **contextual polishers only** — they may slightly influence tone, focus, or domain framing,  
       but **never** change or override the meaning derived from the task content.

    ---
    ## GENERATION RULES

    - Generate a **concise, precise, and factual knowledge query** that captures the information need of the **current task**.
    - If the current task contains **clearly distinct subtopics**, you **may output up to 2 queries** — no more.
    - Each query must:
        * Be self-contained and meaningful for embedding-based retrieval.
        * Exclude irrelevant details, filler text, or stylistic phrases.
        * Directly reflect what information is needed to execute the task successfully.

    ---
    ## OUTPUT FORMAT

    - Output only the knowledge query or queries.
    - One query per line.
    - No explanations, labels, or additional formatting.
    """
)
