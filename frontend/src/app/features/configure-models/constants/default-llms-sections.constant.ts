import { ModelTypes } from '@shared/models';

import { DefaultLlmsSection } from '../interfaces/default-llms-section.interface';

export const DEFAULT_LLMS_SECTIONS: DefaultLlmsSection[] = [
    {
        id: 'agents',
        title: 'For Agents',
        cards: [
            {
                id: 'agent-llm',
                field: 'agent_llm_config',
                title: 'Agent LLM',
                description:
                    'Assigns the default LLM agent and ensures its operation; if necessary, the model can be customized for each agent individually.',
                selectLabel: 'Select LLM from Library',
                icon: 'agent',
                configType: ModelTypes.LLM,
            },
            {
                id: 'agent-fcm-llm',
                field: 'agent_fcm_llm_config',
                title: 'Agent Function Calling LLM',
                description:
                    'The Function Calling LLM handles precise tasks like tool usage and code execution, assigning a recommended model by default.',
                selectLabel: 'Select LLM from Library',
                icon: 'func-calling',
                configType: ModelTypes.LLM,
            },
            {
                id: 'voice-llm',
                field: 'voice_llm_config',
                title: 'Voice LLM',
                description: 'Voice LLM enables real-time spoken interaction by generating immediate voice responses.',
                selectLabel: 'Select LLM from Library',
                icon: 'voice',
                configType: ModelTypes.REALTIME,
            },
            {
                id: 'transcription-llm',
                field: 'transcription_llm_config',
                title: 'Transcription LLM',
                description:
                    'Transcription LLM converts spoken language into accurate written text for further processing.',
                selectLabel: 'Select LLM from Library',
                icon: 'transcription',
                configType: ModelTypes.TRANSCRIPTION,
            },
        ],
    },
    // {
    //     id: 'tools',
    //     title: 'For Tools',
    //     cards: [
    //         {
    //             id: 'tools-embedding-model',
    //             title: 'Tools Embedding Model',
    //             description:
    //                 'Assigns a default Embeddings LLM for all tools, ensuring consistent and accurate embedding management.',
    //             selectLabel: 'Select LLM from Library',
    //             icon: 'llm-agents/tools-embedding',
    //         },
    //         {
    //             id: 'tools-llm',
    //             title: 'Tools LLM',
    //             description:
    //                 'Assigns the default LLM for all tools to ensure consistent operation.',
    //             selectLabel: 'Select LLM from Library',
    //             icon: 'llm-agents/tools',
    //         },
    //     ],
    // },
    // {
    //     id: 'knowledge',
    //     title: 'For Knowledge',
    //     cards: [
    //         {
    //             id: 'knowledge-llm',
    //             title: 'Knowledge LLM',
    //             description:
    //                 'The Knowledge LLM powers information retrieval and understanding for accurate, context-aware responses.',
    //             selectLabel: 'Select LLM from Library',
    //             icon: 'llm-agents/knowledge',
    //         },
    //         {
    //             id: 'knowledge-embedding-model',
    //             title: 'Knowledge Embedding Model',
    //             description:
    //                 'The Knowledge Embedder LLM transforms information into embeddings for efficient search and retrieval.',
    //             selectLabel: 'Select LLM from Library',
    //             icon: 'llm-agents/knowledge-embedding',
    //         },
    //     ],
    // },
];
