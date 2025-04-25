![# crewai-sheets-ui Project](https://repository-images.githubusercontent.com/778369177/0b532ef9-0315-49f6-9edf-83496ae0f399)

<!-- TABLE OF CONTENTS -->

# Motivation

Inspired by the capabilities of CrewAI, I realized the power of automation could be more accessible. This project is about sharing that power—helping friends and colleagues harness AI to streamline their tasks, even if they aren't deep into coding themselves. It’s about making sophisticated technology approachable for anyone interested in automating the routine, allowing them to focus on their passions.

# Features

## Staff
- **GPT Agents**: Offers a set of extendable GPT agents. Choose from predefined options or add your custom agents to fit your specific needs.

## Projects
- **Project Management**: Keep all your crew assignments in one convenient location. Choose and manage projects with a single click, making it simpler to focus on what really matters.

## Tools
- **Extensive Tools Library**: From `crewai-sheets-ui` to `crewai-tools`, including the latest from `langchain` and `langchain-community`.
- **Tool Integration Made Easy**: Add tools from the `langchain` collections directly—just like that.
- **Custom Tool Addition**: Easily configure and integrate your own tools.
- **Executor Tool**: A powerful feature based on `open-interpreter` that runs commands and crafts code for tools not yet supported.

## Model Management
- **Rapid Model Switching**: Switch between LLM models for various functions effortlessly—whether it’s for different agents, tasks, or entire toolsets.
- **Detailed LLM Configurations**: Set precise configurations for each model and tool, offering you full control over their application.
- **Comprehensive Model Support**: Compatible with major LLM providers such as OpenAI, Azure, Anthropic, Groq, and Hugging Face. Integrate any model from these providers with a simple click.

## Local and Online Model Support
- **Local Models**: Fully supports local models, giving you the flexibility to run operations offline or use specific models that aren’t available online.
- **Groq Rate Throttling**: Efficiently utilize Groq’s API without worrying about hitting usage caps.

## User Experience
- **Easy Startup with Docker**: Get started quickly and safely using Docker, ensuring a secure and clean setup.
- **Familiar Interface**: Leveraging a Google Sheets UI, this tool brings advanced automation into an easy-to-use, familiar format, perfect for anyone looking to dive into automation without the steep learning curve.


# Setup Guide for Running with Docker (for users)

This guide provides instructions for setting up and running a Docker container for your application, using various external APIs for enhanced functionality.

## Prerequisites:
- **Check if Docker is installed:**
  - **Windows/Linux/MacOS:** Run `docker --version` in your command prompt or terminal. If Docker is installed, you will see the version number. If not, follow the installation link below.
- **Install Docker (if not installed):**
  - [Docker Installation Guide](https://docs.docker.com/get-docker/)

### API Keys:
You will need to obtain API keys from the following providers. A single API key is sufficient. You don't need all:
Optionally, if you want to run your LLM locally, without a cloud provider, install [Ollama](https://ollama.com/)

- **OpenAI**: [OpenAI API Keys](http://platform.openai.com/)
- **Anthropic API**: [Anthropic API Access](https://www.anthropic.com/api)
- **Groq API**: [Groq API Details](https://console.groq.com/playground) This is FREE at the moment.
- **Hugging Face Hub**: [Hugging Face API Tokens](https://huggingface.co/settings/tokens) Some models FREE at the moment.
- **Azure OpenAI**: [Azure OpenAI Documentation](https://docs.microsoft.com/en-us/azure/cognitive-services/openai/) (mainly for Enterprises)

Optionally, Serper API if you want to use Serper instead of DuckDuckGo.
- **Serper API**: [Serper API Documentation](https://serpapi.com/)

## Running the Container:
- Replace any API KEYS that you have in the below. Do not edit anything else.
- Copy the command for your system to your terminal or powershell.

- **Linux/MacOS:**
```bash
mkdir -p ./savefiles && \
docker build -t crewai-image https://github.com/yuriwa/crewai-sheets-ui.git && \
docker run -it -p 11434:11434 \
  -v $(pwd)/savefiles:/home/user/root/savefiles \
  -e AZURE_OPENAI_KEY='CHANGE THIS TO YOUR AZURE_OPENAI_KEY' \
  -e SECRET_OPENAI_API_KEY='CHANGE THIS TO YOUR SECRET_OPENAI_API_KEY' \
  -e SERPER_API_KEY='CHANGE THIS TO YOUR SERPER_API_KEY' \
  -e AZURE_OPENAI_VERSION='2024-02-15-preview' \
  -e AZURE_OPENAI_API_KEY='CHANGE THIS TO YOUR AZURE_OPENAI_API_KEY' \
  -e AZURE_OPENAI_ENDPOINT='CHANGE THIS TO YOUR AZURE_OPENAI_ENDPOINT' \
  -e ANTHROPIC_API_KEY='CHANGE THIS TO YOUR ANTHROPIC_API_KEY' \
  -e GROQ_API_KEY='CHANGE THIS TO YOUR GROQ_API_KEY' \
  -e HUGGINGFACEHUB_API_TOKEN='CHANGE THIS TO YOUR HUGGINGFACEHUB_API_TOKEN' \
  -e OPENAI_API_KEY='DONT CHANGE THIS USE SECRET OPENAIAPIKEY' \
  crewai-image python /home/user/root/crewai-sheets-ui/main.py

```

- **Windows (PowerShell):**
```
New-Item -ItemType Directory -Path .\savefiles -Force; `
docker build -t crewai-image https://github.com/yuriwa/crewai-sheets-ui.git; `
docker run -it -p 11434:11434 `
  -v ${PWD}\savefiles:/home/user/root/savefiles `
  -e AZURE_OPENAI_KEY='CHANGE THIS TO YOUR AZURE_OPENAI_KEY' `
  -e SECRET_OPENAI_API_KEY='CHANGE THIS TO YOUR SECRET_OPENAI_API_KEY' `
  -e SERPER_API_KEY='CHANGE THIS TO YOUR SERPER_API_KEY' `
  -e AZURE_OPENAI_VERSION='2024-02-15-preview' `
  -e AZURE_OPENAI_API_KEY='CHANGE THIS TO YOUR AZURE_OPENAI_API_KEY' `
  -e AZURE_OPENAI_ENDPOINT='CHANGE THIS TO YOUR AZURE_OPENAI_ENDPOINT' `
  -e ANTHROPIC_API_KEY='CHANGE THIS TO YOUR ANTHROPIC_API_KEY' `
  -e GROQ_API_KEY='CHANGE THIS TO YOUR GROQ_API_KEY' `
  -e HUGGINGFACEHUB_API_TOKEN='CHANGE THIS TO YOUR HUGGINGFACEHUB_API_TOKEN' `
  -e OPENAI_API_KEY='DONT CHANGE THIS USE SECRET OPENAIAPIKEY' `
  crewai-image python /home/user/root/crewai-sheets-ui/main.py
```

### Notes:
- Ensure that each environment variable is set correctly without leading or trailing spaces.
- If you want an alternative setup, i.e., replacing Ollama with LM studio, laamacpp, etc., check network settings and port mappings as per your configuration requirements.
- A folder 'savefiles' will be created in the folder you run this from. This is where the agents will save their work.
- Star the repo to keep motivation up ;)


# Developer setup
To get started with the project, follow these steps:
1. Clone the repository:
   ```
   git clone https://github.com/yuriwa/crewai-sheets-ui.git
   ```
2. Navigate to the project directory:
   ```
   cd crewai-sheets-ui
   ```
3. Install poetry using following command or manually from official installation page:
   ```
   pip install poetry
   poetry --version
   ```
4. Install dependencies using poetry
   - Install all dependencies including those required for development (i.e. pytest, flake8 etc.):
     ```
      poetry install
      ```
   - Or install only the essential dependencies needed to launch the project:
     ```
     poetry install --without dev
     ```
5. Create and configure a `.env` file in the `./src/ENV` directory for storing API keys and other environment variables:
   - Create `ENV` directory in `src` directory if none yet exists:
     ```
     mkdir ./src/ENV
     ```
   - Rename `example.env`:
     ```
     mv example.env ./ENV/.env
     ```
   - Edit `.env` with your specific configurations.
6. Start the application:
   ```
   python ./main.py
   ```

# Usage and first steps.
TODO: 
Hopefully it's intuitive enough meanwhile

# Contributing
Contributions to the crewai-sheets-ui project are welcome. Please ensure to follow the project's code of conduct and submit pull requests for any enhancements or bug fixes.

# Star History

<a href="https://star-history.com/#yuriwa/crewai-sheets-ui&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=yuriwa/crewai-sheets-ui&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=yuriwa/crewai-sheets-ui&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=yuriwa/crewai-sheets-ui&type=Date" />
 </picture>
</a>
